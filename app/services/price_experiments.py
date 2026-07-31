"""Эксперименты с ценами: документы, товары, ежедневные срезы."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import or_

from app.datetime_fmt import format_datetime, local_today
from app.db_sqlite import db_session_commit
from app.extensions import db
from app.models import (
    PriceExperiment,
    PriceExperimentItem,
    PriceExperimentSnapshot,
    Product,
    utcnow,
)
from app.money_fmt import format_money_ru

logger = logging.getLogger(__name__)

# Подписи цен для UI (порядок важен).
PRICE_FIELD_LABELS: tuple[tuple[str, str], ...] = (
    ("price", "Ваша цена"),
    ("promotion_price", "Цена по акции"),
)


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _money_or_none(value) -> float | None:
    amount = _to_float(value)
    if amount is None:
        return None
    return round(amount, 2)


def collect_product_prices(product: Product, prices_api_item: dict | None = None) -> dict:
    """Собирает доступные цены товара из БД и (опционально) ответа /v5/product/info/prices."""
    raw = product.raw_data if isinstance(product.raw_data, dict) else {}
    prices: dict[str, float | None] = {
        "price": _money_or_none(product.price),
        "old_price": _money_or_none(raw.get("old_price")),
        "min_price": _money_or_none(raw.get("min_price")),
        "promotion_price": _money_or_none(product.promotion_price()),
        "marketing_seller_price": None,
    }

    api_price = None
    if isinstance(prices_api_item, dict):
        block = prices_api_item.get("price")
        if isinstance(block, dict):
            api_price = block
        elif any(k in prices_api_item for k in ("price", "old_price", "min_price")):
            api_price = prices_api_item

    if isinstance(api_price, dict):
        for key in ("price", "old_price", "min_price", "marketing_seller_price"):
            value = _money_or_none(api_price.get(key))
            if value is not None:
                prices[key] = value
        marketing = _money_or_none(api_price.get("marketing_price"))
        if marketing is not None and marketing > 0:
            prices["marketing_price"] = marketing
        retail = _money_or_none(api_price.get("retail_price"))
        if retail is not None and retail > 0:
            prices["retail_price"] = retail

    return prices


def _format_prices_for_ui(prices: dict | None) -> list[dict]:
    data = prices if isinstance(prices, dict) else {}
    rows: list[dict] = []
    for key, label in PRICE_FIELD_LABELS:
        value = data.get(key)
        rows.append({
            "key": key,
            "label": label,
            "value": value,
            "display": format_money_ru(value) if value is not None else "—",
            "change": None,
        })
    return rows


def _change_direction(current, previous) -> str | None:
    """up / down относительно предыдущего среза; None если сравнить нельзя или без изменений."""
    cur = _to_float(current)
    prev = _to_float(previous)
    if cur is None or prev is None:
        return None
    if abs(cur - prev) < 0.0001:
        return None
    return "up" if cur > prev else "down"


def _collect_profit_markup(product: Product) -> list[dict]:
    """Снимок прибыли/наценки как на странице Товары."""
    from app.services.product_profit import profit_markup_scheme_rows

    rows = []
    for scheme_label, line, negative in profit_markup_scheme_rows(product):
        rows.append({
            "scheme_label": scheme_label,
            "line": line,
            "negative": bool(negative),
        })
    return rows


def _snapshot_to_dict(snapshot: PriceExperimentSnapshot) -> dict:
    prices = snapshot.prices if isinstance(snapshot.prices, dict) else {}
    profit_rows = snapshot.profit_markup if isinstance(snapshot.profit_markup, list) else []
    return {
        "id": snapshot.id,
        "snapshot_date": snapshot.snapshot_date.isoformat() if snapshot.snapshot_date else None,
        "snapshot_date_display": (
            snapshot.snapshot_date.strftime("%d.%m.%Y") if snapshot.snapshot_date else "—"
        ),
        "stock_fbo": snapshot.stock_fbo or 0,
        "stock_fbs": snapshot.stock_fbs or 0,
        "stock_fbo_change": None,
        "stock_fbs_change": None,
        "purchase_price": float(snapshot.purchase_price) if snapshot.purchase_price is not None else None,
        "purchase_price_display": format_money_ru(snapshot.purchase_price),
        "purchase_price_change": None,
        "prices": prices,
        "prices_list": _format_prices_for_ui(prices),
        "profit_markup": profit_rows,
        "source": snapshot.source,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
    }


def _attach_snapshot_changes(snapshots: list[dict]) -> list[dict]:
    """Сравнивает каждый срез с более ранним (список от новых к старым)."""
    for index, snap in enumerate(snapshots):
        if index + 1 >= len(snapshots):
            break
        prev = snapshots[index + 1]
        snap["stock_fbo_change"] = _change_direction(snap.get("stock_fbo"), prev.get("stock_fbo"))
        snap["stock_fbs_change"] = _change_direction(snap.get("stock_fbs"), prev.get("stock_fbs"))
        snap["purchase_price_change"] = _change_direction(
            snap.get("purchase_price"),
            prev.get("purchase_price"),
        )
        prev_prices = {
            row["key"]: row.get("value")
            for row in (prev.get("prices_list") or [])
            if isinstance(row, dict)
        }
        for row in snap.get("prices_list") or []:
            if not isinstance(row, dict):
                continue
            row["change"] = _change_direction(row.get("value"), prev_prices.get(row.get("key")))
    return snapshots


def _item_to_dict(item: PriceExperimentItem, *, include_history: bool = False) -> dict:
    product = item.product
    snapshots = list(item.snapshots or [])
    latest = snapshots[0] if snapshots else None
    data = {
        "id": item.id,
        "product_id": item.product_id,
        "comment": item.comment or "",
        "added_at": item.added_at.isoformat() if item.added_at else None,
        "added_at_display": format_datetime(item.added_at, "%d.%m.%Y в %H:%M") if item.added_at else "—",
        "product": {
            "id": product.id if product else None,
            "name": product.name if product else "—",
            "offer_id": product.offer_id if product else "—",
            "barcode": product.barcode_display() if product else "—",
            "thumbnail_url": product.thumbnail_url if product else None,
            "ozon_url": product.ozon_marketplace_url() if product else None,
        },
        "latest": _snapshot_to_dict(latest) if latest else None,
        "snapshots_count": len(snapshots),
    }
    if include_history:
        history = [_snapshot_to_dict(s) for s in snapshots]
        data["snapshots"] = _attach_snapshot_changes(history)
    return data


def _experiment_to_dict(experiment: PriceExperiment, *, with_items: bool = False) -> dict:
    items = list(experiment.items or [])
    is_running = experiment.status == PriceExperiment.STATUS_ACTIVE
    data = {
        "id": experiment.id,
        "title": experiment.title,
        "note": experiment.note or "",
        "status": experiment.status,
        "is_running": is_running,
        "created_at": experiment.created_at.isoformat() if experiment.created_at else None,
        "created_at_display": (
            format_datetime(experiment.created_at, "%d.%m.%Y в %H:%M")
            if experiment.created_at
            else "—"
        ),
        "updated_at": experiment.updated_at.isoformat() if experiment.updated_at else None,
        "items_count": len(items),
    }
    if with_items:
        data["items"] = [_item_to_dict(item, include_history=True) for item in items]
    return data


def is_snapshot_task_enabled(user_id: int) -> bool:
    """Включено ли регламентное задание ежедневных срезов."""
    from app.models import ScheduledTaskSetting
    from app.services.scheduled_tasks_service import ensure_user_task_settings

    ensure_user_task_settings(user_id)
    setting = ScheduledTaskSetting.query.filter_by(
        user_id=user_id,
        task_slug="price_experiments_snapshot",
    ).first()
    return bool(setting and setting.enabled)


def list_experiments(user_id: int) -> list[dict]:
    rows = (
        PriceExperiment.query.filter_by(user_id=user_id)
        .order_by(PriceExperiment.created_at.desc())
        .all()
    )
    return [_experiment_to_dict(row) for row in rows]


def get_experiment(user_id: int, experiment_id: int) -> dict | None:
    experiment = PriceExperiment.query.filter_by(id=experiment_id, user_id=user_id).first()
    if not experiment:
        return None
    return _experiment_to_dict(experiment, with_items=True)


def create_experiment(user_id: int, title: str, note: str | None = None) -> dict:
    title_clean = (title or "").strip()
    if not title_clean:
        return {"ok": False, "error": "Укажите название эксперимента."}

    experiment = PriceExperiment(
        user_id=user_id,
        title=title_clean[:256],
        note=(note or "").strip() or None,
        status=PriceExperiment.STATUS_ACTIVE,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.session.add(experiment)
    db_session_commit()
    return {"ok": True, "experiment": _experiment_to_dict(experiment, with_items=True)}


def update_experiment(user_id: int, experiment_id: int, title: str, note: str | None = None) -> dict:
    experiment = PriceExperiment.query.filter_by(id=experiment_id, user_id=user_id).first()
    if not experiment:
        return {"ok": False, "error": "Эксперимент не найден."}

    title_clean = (title or "").strip()
    if not title_clean:
        return {"ok": False, "error": "Укажите название эксперимента."}

    experiment.title = title_clean[:256]
    experiment.note = (note or "").strip() or None
    experiment.updated_at = utcnow()
    db_session_commit()
    return {"ok": True, "experiment": _experiment_to_dict(experiment, with_items=True)}


def set_experiment_running(user_id: int, experiment_id: int, running: bool) -> dict:
    experiment = PriceExperiment.query.filter_by(id=experiment_id, user_id=user_id).first()
    if not experiment:
        return {"ok": False, "error": "Эксперимент не найден."}

    experiment.status = (
        PriceExperiment.STATUS_ACTIVE if running else PriceExperiment.STATUS_STOPPED
    )
    experiment.updated_at = utcnow()
    db_session_commit()
    return {
        "ok": True,
        "experiment": _experiment_to_dict(experiment, with_items=False),
        "message": "Эксперимент запущен." if running else "Эксперимент остановлен.",
    }


def delete_experiment(user_id: int, experiment_id: int) -> dict:
    experiment = PriceExperiment.query.filter_by(id=experiment_id, user_id=user_id).first()
    if not experiment:
        return {"ok": False, "error": "Эксперимент не найден."}
    db.session.delete(experiment)
    db_session_commit()
    return {"ok": True}


def search_products_for_experiment(user_id: int, query: str, *, limit: int = 20) -> list[dict]:
    text = (query or "").strip()
    if len(text) < 2:
        return []

    like = f"%{text}%"
    rows = (
        Product.query.filter(
            Product.user_id == user_id,
            or_(
                Product.name.ilike(like),
                Product.offer_id.ilike(like),
                Product.barcode.ilike(like),
                Product.sku.ilike(like),
            ),
        )
        .order_by(Product.name.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": p.id,
            "name": p.name,
            "offer_id": p.offer_id or "—",
            "barcode": p.barcode_display(),
            "thumbnail_url": p.thumbnail_url,
            "stock_fbo": p.stock_fbo or 0,
            "stock_fbs": p.stock_fbs or 0,
            "purchase_price_display": format_money_ru(p.purchase_price),
            "price_display": format_money_ru(p.effective_sale_price()),
        }
        for p in rows
    ]


def _fetch_prices_api_map(user, product_ids: list[str]) -> dict[str, dict]:
    if not user.has_ozon_credentials() or not product_ids:
        return {}
    try:
        from app.ozon.product_prices import fetch_products_prices

        items = fetch_products_prices(user.ozon_client_id, user.ozon_api_key, product_ids)
    except Exception as exc:
        logger.warning("price experiments: prices API failed: %s", exc)
        return {}

    result: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("product_id") or item.get("id") or "").strip()
        if pid:
            result[pid] = item
    return result


def _upsert_snapshot(
    item: PriceExperimentItem,
    *,
    snapshot_date: date,
    source: str,
    prices_api_item: dict | None = None,
) -> PriceExperimentSnapshot:
    product = item.product
    if not product:
        raise ValueError("Товар эксперимента не найден.")

    prices = collect_product_prices(product, prices_api_item)
    profit_markup = _collect_profit_markup(product)
    existing = PriceExperimentSnapshot.query.filter_by(
        item_id=item.id,
        snapshot_date=snapshot_date,
    ).first()

    if existing:
        existing.stock_fbo = int(product.stock_fbo or 0)
        existing.stock_fbs = int(product.stock_fbs or 0)
        existing.purchase_price = product.purchase_price
        existing.prices = prices
        existing.profit_markup = profit_markup
        if existing.source != PriceExperimentSnapshot.SOURCE_ADD:
            existing.source = source
        return existing

    snapshot = PriceExperimentSnapshot(
        item_id=item.id,
        snapshot_date=snapshot_date,
        stock_fbo=int(product.stock_fbo or 0),
        stock_fbs=int(product.stock_fbs or 0),
        purchase_price=product.purchase_price,
        prices=prices,
        profit_markup=profit_markup,
        source=source,
        created_at=utcnow(),
    )
    db.session.add(snapshot)
    return snapshot


def add_products_to_experiment(
    user,
    experiment_id: int,
    product_ids: list[int],
    comment: str | None = None,
) -> dict:
    experiment = PriceExperiment.query.filter_by(id=experiment_id, user_id=user.id).first()
    if not experiment:
        return {"ok": False, "error": "Эксперимент не найден."}

    ids: list[int] = []
    seen: set[int] = set()
    for raw_id in product_ids:
        try:
            pid = int(raw_id)
        except (TypeError, ValueError):
            continue
        if pid in seen:
            continue
        seen.add(pid)
        ids.append(pid)

    if not ids:
        return {"ok": False, "error": "Не выбран ни один товар."}

    products = (
        Product.query.filter(Product.user_id == user.id, Product.id.in_(ids)).all()
    )
    products_by_id = {p.id: p for p in products}
    if len(products_by_id) != len(ids):
        return {"ok": False, "error": "Один или несколько товаров не найдены."}

    already = {
        row.product_id
        for row in PriceExperimentItem.query.filter(
            PriceExperimentItem.experiment_id == experiment.id,
            PriceExperimentItem.product_id.in_(ids),
        ).all()
    }
    to_add = [pid for pid in ids if pid not in already]
    if not to_add:
        return {"ok": False, "error": "Все выбранные товары уже есть в эксперименте."}

    comment_clean = (comment or "").strip() or None
    ozon_ids = [str(products_by_id[pid].ozon_product_id) for pid in to_add]
    prices_map = _fetch_prices_api_map(user, ozon_ids)
    today = local_today()
    added_items: list[dict] = []

    for pid in to_add:
        product = products_by_id[pid]
        item = PriceExperimentItem(
            experiment_id=experiment.id,
            product_id=product.id,
            comment=comment_clean,
            added_at=utcnow(),
        )
        db.session.add(item)
        db.session.flush()
        _upsert_snapshot(
            item,
            snapshot_date=today,
            source=PriceExperimentSnapshot.SOURCE_ADD,
            prices_api_item=prices_map.get(str(product.ozon_product_id)),
        )
        added_items.append(_item_to_dict(item, include_history=True))

    experiment.updated_at = utcnow()
    db_session_commit()

    skipped = len(ids) - len(to_add)
    message = f"Добавлено товаров: {len(to_add)}."
    if skipped:
        message += f" Пропущено (уже были): {skipped}."

    return {
        "ok": True,
        "added": len(to_add),
        "skipped": skipped,
        "items": added_items,
        "message": message,
    }


def add_product_to_experiment(
    user,
    experiment_id: int,
    product_id: int,
    comment: str | None = None,
) -> dict:
    result = add_products_to_experiment(user, experiment_id, [product_id], comment=comment)
    if result.get("ok") and result.get("items"):
        result["item"] = result["items"][0]
    return result


def update_item_comment(user_id: int, item_id: int, comment: str | None) -> dict:
    item = (
        PriceExperimentItem.query.join(PriceExperiment)
        .filter(
            PriceExperimentItem.id == item_id,
            PriceExperiment.user_id == user_id,
        )
        .first()
    )
    if not item:
        return {"ok": False, "error": "Товар эксперимента не найден."}

    item.comment = (comment or "").strip() or None
    item.experiment.updated_at = utcnow()
    db_session_commit()
    return {"ok": True, "item": _item_to_dict(item, include_history=True)}


def remove_item(user_id: int, item_id: int) -> dict:
    item = (
        PriceExperimentItem.query.join(PriceExperiment)
        .filter(
            PriceExperimentItem.id == item_id,
            PriceExperiment.user_id == user_id,
        )
        .first()
    )
    if not item:
        return {"ok": False, "error": "Товар эксперимента не найден."}

    experiment = item.experiment
    db.session.delete(item)
    if experiment:
        experiment.updated_at = utcnow()
    db_session_commit()
    return {"ok": True}


def update_item_sale_price(user, item_id: int, new_price) -> dict:
    """Меняет «Вашу цену» товара через Ozon API и обновляет сегодняшний срез."""
    from decimal import Decimal

    from app.ozon.product_prices import update_product_prices
    from app.services.purchase_prices import _parse_price

    item = (
        PriceExperimentItem.query.join(PriceExperiment)
        .filter(
            PriceExperimentItem.id == item_id,
            PriceExperiment.user_id == user.id,
        )
        .first()
    )
    if not item:
        return {"ok": False, "error": "Товар эксперимента не найден."}

    product = item.product
    if not product:
        return {"ok": False, "error": "Товар не найден."}
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле."}

    price = _parse_price(new_price)
    if price is None or price <= 0:
        return {"ok": False, "error": "Укажите корректную цену больше нуля."}

    price = price.quantize(Decimal("0.01"))
    current = _to_float(product.price)
    if current is not None and abs(float(price) - current) < 0.0001:
        return {
            "ok": True,
            "unchanged": True,
            "price": float(price),
            "price_display": format_money_ru(price),
            "message": "Цена не изменилась.",
        }

    raw = product.raw_data if isinstance(product.raw_data, dict) else {}
    payload_item: dict = {
        "product_id": int(product.ozon_product_id),
        "price": f"{price:.2f}",
        "currency_code": "RUB",
        "auto_action_enabled": "UNKNOWN",
    }
    old_price = _money_or_none(raw.get("old_price"))
    if old_price is not None and old_price > 0:
        payload_item["old_price"] = f"{old_price:.2f}"
    min_price = _money_or_none(raw.get("min_price"))
    if min_price is not None and min_price > 0:
        payload_item["min_price"] = f"{min_price:.2f}"

    try:
        api_result = update_product_prices(
            user.ozon_client_id,
            user.ozon_api_key,
            [payload_item],
        )
    except Exception as exc:
        logger.exception("price experiments: update price failed")
        return {"ok": False, "error": str(exc)}

    if not api_result.get("ok"):
        return {"ok": False, "error": api_result.get("error") or "Ozon не принял цену."}

    product.price = price
    if isinstance(product.raw_data, dict):
        updated_raw = dict(product.raw_data)
    else:
        updated_raw = {}
    updated_raw["price"] = f"{price:.2f}"
    product.raw_data = updated_raw

    prices_map = _fetch_prices_api_map(user, [str(product.ozon_product_id)])
    _upsert_snapshot(
        item,
        snapshot_date=local_today(),
        source=PriceExperimentSnapshot.SOURCE_MANUAL,
        prices_api_item=prices_map.get(str(product.ozon_product_id)),
    )
    item.experiment.updated_at = utcnow()
    db_session_commit()

    result = {
        "ok": True,
        "price": float(price),
        "price_display": format_money_ru(price),
        "message": "Цена обновлена в Ozon.",
        "item": _item_to_dict(item, include_history=True),
    }
    if api_result.get("warning"):
        result["warning"] = api_result["warning"]
    return result


def take_daily_snapshots(user, experiment_id: int | None = None) -> dict:
    """Снимает ежедневный срез.

    Без experiment_id — только запущенные эксперименты (регламент).
    С experiment_id — указанный эксперимент независимо от Пуск/Стоп (ручной срез).
    """
    query = PriceExperimentItem.query.join(PriceExperiment).filter(
        PriceExperiment.user_id == user.id,
    )
    if experiment_id is not None:
        query = query.filter(PriceExperiment.id == experiment_id)
    else:
        query = query.filter(PriceExperiment.status == PriceExperiment.STATUS_ACTIVE)

    items = query.all()
    if not items:
        if experiment_id is not None:
            experiment = PriceExperiment.query.filter_by(
                id=experiment_id,
                user_id=user.id,
            ).first()
            if not experiment:
                return {"ok": False, "error": "Эксперимент не найден."}
            return {"ok": True, "created": 0, "updated": 0, "message": "В эксперименте нет товаров."}
        return {"ok": True, "created": 0, "updated": 0, "message": "Нет запущенных экспериментов."}

    product_ids = [
        str(item.product.ozon_product_id)
        for item in items
        if item.product and item.product.ozon_product_id
    ]
    prices_map = _fetch_prices_api_map(user, product_ids)
    today = local_today()
    created = 0
    updated = 0
    source = (
        PriceExperimentSnapshot.SOURCE_MANUAL
        if experiment_id is not None
        else PriceExperimentSnapshot.SOURCE_DAILY
    )

    for item in items:
        if not item.product:
            continue
        before = PriceExperimentSnapshot.query.filter_by(
            item_id=item.id,
            snapshot_date=today,
        ).first()
        _upsert_snapshot(
            item,
            snapshot_date=today,
            source=source,
            prices_api_item=prices_map.get(str(item.product.ozon_product_id)),
        )
        if before:
            updated += 1
        else:
            created += 1

    db_session_commit()
    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "message": f"Срезы за {today.strftime('%d.%m.%Y')}: новых {created}, обновлено {updated}.",
    }


def take_snapshots_for_all_users() -> dict:
    from app.models import User

    users = User.query.filter_by(is_active=True).all()
    total_created = 0
    total_updated = 0
    for user in users:
        result = take_daily_snapshots(user)
        total_created += int(result.get("created") or 0)
        total_updated += int(result.get("updated") or 0)
    return {
        "ok": True,
        "created": total_created,
        "updated": total_updated,
        "message": f"Срезы экспериментов: новых {total_created}, обновлено {total_updated}.",
    }
