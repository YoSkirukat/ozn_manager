"""Синхронизация заказов Ozon в локальную БД."""

from datetime import date

from app.db_sqlite import db_session_commit
from app.extensions import db
from app.models import ORDER_STATUS_DELIVERED, Order, utcnow
from app.ozon.orders import fetch_fbo_postings, fetch_fbs_postings
from app.services.change_log import log_change
from app.services.order_details import (
    _cached_margin,
    clear_financial_cache,
    compute_order_margin,
    merge_order_raw_data,
    resolve_total_accrued,
)
from app.services.order_buyout import build_buyout_index_for_orders, clear_buyout_cache
from app.services.order_images import resolve_thumbnail_url
from app.services.order_promotions import apply_product_promotions, fetch_known_promotion_titles

SYNC_COMMIT_BATCH = 20
FINANCIAL_COMMIT_BATCH = 5


def _refresh_orders_financials_batch(user, orders: list[Order]) -> dict:
    """Пакетно обновляет начисления/маржу и кэширует их в raw_data."""
    if not orders:
        return {"processed": 0, "updated": 0}

    from app.services.order_details import _product_lookup  # локальный импорт для избежания циклов

    product_lookup = _product_lookup(user.id)
    updated = 0
    buyout_index = build_buyout_index_for_orders(user, orders)

    with db.session.no_autoflush:
        for index, order in enumerate(orders, start=1):
            if order.status != ORDER_STATUS_DELIVERED:
                continue
            before_raw = dict(order.raw_data) if isinstance(order.raw_data, dict) else {}
            clear_financial_cache(order)
            if order.is_international():
                clear_buyout_cache(order)
            raw = order.raw_data if isinstance(order.raw_data, dict) else before_raw
            if not order.is_international():
                resolve_total_accrued(order, raw, user=user, use_transactions=True)
            compute_order_margin(
                order,
                user=user,
                use_transactions=True,
                product_lookup=product_lookup,
                buyout_index=buyout_index,
            )
            after_raw = order.raw_data if isinstance(order.raw_data, dict) else {}
            if after_raw != before_raw:
                updated += 1
            if index % FINANCIAL_COMMIT_BATCH == 0:
                db_session_commit()

    db_session_commit()
    return {"processed": len(orders), "updated": updated}


def _recompute_local_margins(user, orders: list[Order]) -> int:
    """Локальный пересчёт маржи без API для заказов без кэша."""
    if not orders:
        return 0

    from app.services.order_details import _product_lookup

    product_lookup = _product_lookup(user.id)
    recomputed = 0

    with db.session.no_autoflush:
        for order in orders:
            if order.status != ORDER_STATUS_DELIVERED:
                continue
            raw = order.raw_data if isinstance(order.raw_data, dict) else {}
            if _cached_margin(raw) is not None and not order.is_international():
                continue
            compute_order_margin(
                order,
                user=user,
                use_transactions=False,
                product_lookup=product_lookup,
            )
            recomputed += 1

    return recomputed


def load_orders_from_ozon(
    user,
    date_from: date,
    date_to: date,
    *,
    refresh_financials_batch: bool = False,
) -> dict:
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле."}

    if date_from > date_to:
        return {"ok": False, "error": "Дата начала не может быть позже даты окончания."}

    if (date_to - date_from).days > 365:
        return {"ok": False, "error": "Максимальный период загрузки — 365 дней."}

    client_id = user.ozon_client_id
    api_key = user.ozon_api_key

    try:
        fbs_items = fetch_fbs_postings(client_id, api_key, date_from, date_to)
        fbo_items = fetch_fbo_postings(client_id, api_key, date_from, date_to)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    all_items = fbs_items + fbo_items
    created = 0
    updated = 0
    now = utcnow()

    known_promotion_titles: set[str] = set()
    try:
        known_promotion_titles = fetch_known_promotion_titles(client_id, api_key)
    except Exception:
        known_promotion_titles = set()

    touched_orders: list[Order] = []
    new_ozon_ids: list[str] = []
    with db.session.no_autoflush:
        for index, item in enumerate(all_items, start=1):
            order = Order.query.filter_by(
                user_id=user.id,
                ozon_order_id=item["ozon_order_id"],
            ).first()

            thumb = resolve_thumbnail_url(user.id, item.get("raw_data"))
            merged_raw = merge_order_raw_data(
                order.raw_data if order and isinstance(order.raw_data, dict) else None,
                item.get("raw_data"),
                old_status=order.status if order else "",
                new_status=item["status"],
            )

            if order:
                order.status = item["status"]
                order.scheme = item["scheme"]
                order.total = item["total"]
                order.order_date = item["order_date"]
                order.raw_data = merged_raw
                if thumb:
                    order.thumbnail_url = thumb
                updated += 1
                touched_orders.append(order)
            else:
                order = Order(
                    user_id=user.id,
                    ozon_order_id=item["ozon_order_id"],
                    status=item["status"],
                    scheme=item["scheme"],
                    total=item["total"],
                    order_date=item["order_date"],
                    thumbnail_url=thumb,
                    raw_data=merged_raw,
                    created_at=now,
                )
                db.session.add(order)
                created += 1
                new_ozon_ids.append(item["ozon_order_id"])
                touched_orders.append(order)

            apply_product_promotions(
                order,
                user_id=user.id,
                known_titles=known_promotion_titles,
                force_refresh=True,
            )

            if index % SYNC_COMMIT_BATCH == 0:
                db_session_commit()

    financials = {"processed": 0, "updated": 0}
    margins_recomputed = 0
    if refresh_financials_batch and touched_orders:
        financials = _refresh_orders_financials_batch(user, touched_orders)
    elif touched_orders:
        margins_recomputed = _recompute_local_margins(user, touched_orders)

    log_change(
        user_id=user.id,
        action_type="update",
        entity_type="order",
        entity_id=0,
        old_value=None,
        new_value={
            "sync": "ozon",
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "created": created,
            "updated": updated,
            "total": len(all_items),
            "fbs": len(fbs_items),
            "fbo": len(fbo_items),
            "financials_processed": financials.get("processed", 0),
            "financials_updated": financials.get("updated", 0),
            "margins_recomputed": margins_recomputed,
        },
    )
    db_session_commit()

    if new_ozon_ids:
        from app.services.notifications_service import notify_new_orders

        new_orders = Order.query.filter(
            Order.user_id == user.id,
            Order.ozon_order_id.in_(new_ozon_ids),
        ).all()
        notify_new_orders(user, new_orders)

    message = (
        f"Загружено заказов: {len(all_items)} "
        f"(FBS {len(fbs_items)}, FBO {len(fbo_items)}; новых {created}, обновлено {updated})."
    )
    if refresh_financials_batch:
        message += f" Финансы пересчитаны: {financials.get('updated', 0)}."
    elif margins_recomputed:
        message += f" Маржа пересчитана локально: {margins_recomputed}."

    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "total": len(all_items),
        "fbs": len(fbs_items),
        "fbo": len(fbo_items),
        "financials_processed": financials.get("processed", 0),
        "financials_updated": financials.get("updated", 0),
        "margins_recomputed": margins_recomputed,
        "message": message,
    }
