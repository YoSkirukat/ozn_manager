"""Синхронизация товаров из Ozon Seller API в локальную БД."""

from app.db_sqlite import db_session_commit
from app.extensions import db
from app.models import Product, utcnow
from app.ozon.client import fetch_product_list, fetch_products_info, normalize_product_item
from app.ozon.product_prices import fetch_products_prices
from app.services.product_commissions import extract_product_commissions
from app.services.product_actions import (
    promotion_prices_map_from_collected,
    promotions_map_from_collected,
    sync_promotion_memberships_from_ozon,
    update_user_products_in_promotions_count,
    _collect_active_promotions,
)
from app.services.promotion_membership import sync_promotion_memberships
from app.services.change_log import log_change
from app.services.purchase_prices import apply_purchase_prices


def _preserve_external_fbs_stocks(user) -> bool:
    return bool((getattr(user, "fbs_stocks_url", None) or "").strip())


def sync_products_from_ozon(user) -> dict:
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле."}

    client_id = user.ozon_client_id
    api_key = user.ozon_api_key

    try:
        list_items = fetch_product_list(client_id, api_key)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    product_ids = []
    offer_by_pid = {}
    for row in list_items:
        pid = str(row.get("product_id") or row.get("id") or "")
        if pid:
            product_ids.append(pid)
            offer_by_pid[pid] = str(row.get("offer_id") or "")

    if not product_ids:
        user.products_in_promotions_count = 0
        prices_result = apply_purchase_prices(user)
        db_session_commit()
        promotions_sync = sync_promotion_memberships_from_ozon(user)
        return _build_sync_result(
            ok=True,
            created=0,
            updated=0,
            total=0,
            prices_result=prices_result,
            promotions_sync=promotions_sync,
            base_message="В кабинете нет товаров.",
        )

    try:
        info_items = fetch_products_info(client_id, api_key, product_ids)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    prices_by_pid: dict[str, dict] = {}
    try:
        for price_item in fetch_products_prices(client_id, api_key, product_ids):
            pid = str(price_item.get("product_id") or "")
            if pid:
                prices_by_pid[pid] = price_item
    except Exception as exc:
        return {"ok": False, "error": f"Комиссии: {exc}"}

    promotions_map: dict[str, list[str]] = {}
    promotions_sync: dict = {"ok": False}
    try:
        collected_promotions = _collect_active_promotions(client_id, api_key)
        promotions_map = promotions_map_from_collected(collected_promotions)
        promotions_price_map = promotion_prices_map_from_collected(collected_promotions)
        sync_promotion_memberships(user.id, collected_promotions)
        unique_promo_products = {
            str(product.get("ozon_product_id") or "").strip()
            for promo in collected_promotions
            for product in promo.get("products") or []
            if str(product.get("ozon_product_id") or "").strip()
        }
        promotions_sync = {
            "ok": True,
            "promotion_count": len(collected_promotions),
            "product_count": len(unique_promo_products),
        }
    except Exception as exc:
        promotions_sync = {"ok": False, "error": str(exc)}

    now = utcnow()
    created = 0
    updated = 0
    preserve_fbs = _preserve_external_fbs_stocks(user)

    for item in info_items:
        normalized = normalize_product_item(item)
        pid = normalized["ozon_product_id"]
        if not pid:
            continue
        if not normalized["offer_id"]:
            normalized["offer_id"] = offer_by_pid.get(pid, "")

        promo_price = promotions_price_map.get(pid)
        sale_price = float(normalized["price"])
        if promo_price is not None and float(promo_price) > 0:
            sale_price = float(promo_price)

        commissions = extract_product_commissions(
            prices_by_pid.get(pid),
            item,
            sale_price,
        )

        raw_data = normalized["raw_data"]
        promo_patch = {
            "active_promotions": promotions_map.get(pid, []),
            "promotion_price": promo_price,
        }
        if isinstance(raw_data, dict):
            raw_data = {**raw_data, **promo_patch}
        else:
            raw_data = promo_patch

        product = Product.query.filter_by(
            user_id=user.id,
            ozon_product_id=pid,
        ).first()

        if product:
            product.offer_id = normalized["offer_id"]
            product.barcode = normalized["barcode"]
            product.thumbnail_url = normalized["thumbnail_url"]
            product.sku = normalized["sku"]
            product.name = normalized["name"]
            product.price = normalized["price"]
            product.stock_fbo = normalized["stock_fbo"]
            if not preserve_fbs:
                product.stock_fbs = normalized["stock_fbs"]
            product.commission_fbo = commissions["fbo_total"]
            product.commission_fbs = commissions["fbs_total"]
            product.commission_details = commissions["details"]
            product.raw_data = raw_data
            product.last_sync = now
            updated += 1
        else:
            product = Product(
                user_id=user.id,
                ozon_product_id=pid,
                offer_id=normalized["offer_id"],
                barcode=normalized["barcode"],
                thumbnail_url=normalized["thumbnail_url"],
                sku=normalized["sku"],
                name=normalized["name"],
                price=normalized["price"],
                stock_fbo=normalized["stock_fbo"],
                stock_fbs=normalized["stock_fbs"],
                commission_fbo=commissions["fbo_total"],
                commission_fbs=commissions["fbs_total"],
                commission_details=commissions["details"],
                raw_data=raw_data,
                last_sync=now,
            )
            db.session.add(product)
            created += 1

    update_user_products_in_promotions_count(user)

    log_change(
        user_id=user.id,
        action_type="update",
        entity_type="product",
        entity_id=0,
        old_value=None,
        new_value={
            "sync": "ozon",
            "created": created,
            "updated": updated,
            "total": len(info_items),
        },
    )

    prices_result = apply_purchase_prices(user)
    db_session_commit()

    return _build_sync_result(
        ok=True,
        created=created,
        updated=updated,
        total=len(info_items),
        prices_result=prices_result,
        promotions_sync=promotions_sync,
    )


def _build_sync_result(
    *,
    ok: bool,
    created: int,
    updated: int,
    total: int,
    prices_result: dict | None = None,
    promotions_sync: dict | None = None,
    base_message: str | None = None,
    error: str | None = None,
) -> dict:
    if not ok:
        return {"ok": False, "error": error}

    message = base_message or f"Синхронизировано: {total} (новых {created}, обновлено {updated})."
    result = {
        "ok": True,
        "created": created,
        "updated": updated,
        "total": total,
        "message": message,
    }

    if promotions_sync:
        result["promotions_sync"] = promotions_sync
        if promotions_sync.get("ok"):
            result["promotions_count"] = promotions_sync.get("promotion_count", 0)
            result["promotions_product_count"] = promotions_sync.get("product_count", 0)
            promo_msg = (
                f"Акции: {promotions_sync.get('promotion_count', 0)}, "
                f"товаров в акциях {promotions_sync.get('product_count', 0)}."
            )
            result["message"] = f"{message} {promo_msg}"
        elif promotions_sync.get("error"):
            result["promotions_sync_error"] = promotions_sync["error"]
            result["message"] = f"{message} Акции: {promotions_sync['error']}."

    if not prices_result or prices_result.get("skipped"):
        return result

    if prices_result.get("ok"):
        result["purchase_prices_updated"] = prices_result.get("updated", 0)
        price_msg = prices_result.get("message")
        if price_msg:
            result["message"] = f"{result['message']} {price_msg}"
    else:
        result["purchase_prices_error"] = prices_result.get("error")
        result["message"] = f"{result['message']} Закупочные цены: {prices_result.get('error')}."

    return result
