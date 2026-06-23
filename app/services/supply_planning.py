"""Планирование поставки: движение товара по складу за период."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from app.datetime_fmt import local_today, utc_bounds_for_local_dates
from app.models import ORDER_STATUS_DELIVERED, Product, Shipment
from app.ozon.stocks import fetch_stock_rows
from app.ozon.supplies import fetch_bundle_items
from app.services.stock_report import get_stock_report_cache
from app.services.supply_sync import load_supplies_from_ozon

SUPPLY_RECEIVED_STATUSES = frozenset({
    "ACCEPTED_AT_STORAGE_WAREHOUSE",
    "ACCEPTANCE_AT_STORAGE_WAREHOUSE",
    "REPORTS_FILLING",
    "REPORTS_CONFIRMATION_AWAITING",
    "REPORT_REJECTED",
    "COMPLETED",
})


def normalize_warehouse_name(name: str | None) -> str:
    if not name:
        return ""
    text = str(name).strip().upper().replace("-", "_").replace(" ", "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text


def warehouse_names_match(left: str | None, right: str | None) -> bool:
    left_norm = normalize_warehouse_name(left)
    right_norm = normalize_warehouse_name(right)
    return bool(left_norm) and left_norm == right_norm


def _product_key(offer_id: str | None, sku: str | None = None) -> str:
    offer = str(offer_id or "").strip()
    if offer and offer != "—":
        return f"offer:{offer}"
    sku_text = str(sku or "").strip()
    if sku_text:
        return f"sku:{sku_text}"
    return "unknown"


def _warehouse_stock_rows(rows: list[dict], warehouse_name: str) -> list[dict]:
    target = normalize_warehouse_name(warehouse_name)
    items = []
    for row in rows:
        if normalize_warehouse_name(row.get("warehouse_name")) != target:
            continue
        free_qty = int(row.get("free_to_sell_amount") or 0)
        reserved = int(row.get("reserved_amount") or 0)
        promised = int(row.get("promised_amount") or 0)
        qty = free_qty + reserved + promised
        if qty <= 0:
            continue
        items.append(
            {
                "sku": str(row.get("sku") or ""),
                "offer_id": str(row.get("item_code") or "—"),
                "name": str(row.get("item_name") or "—"),
                "quantity": qty,
            }
        )
    return items


def _catalog_lookup(user_id: int) -> dict[str, Product]:
    lookup: dict[str, Product] = {}
    for product in Product.query.filter_by(user_id=user_id).all():
        if product.offer_id:
            lookup[f"offer:{product.offer_id}"] = product
        if product.sku:
            lookup[f"sku:{product.sku}"] = product
        if product.ozon_product_id:
            lookup[f"sku:{product.ozon_product_id}"] = product
    return lookup


def _resolve_product_meta(
    key: str,
    *,
    catalog: dict[str, Product],
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    product = catalog.get(key)
    fallback = fallback or {}
    offer_id = (
        product.offer_id
        if product and product.offer_id
        else str(fallback.get("offer_id") or "—")
    )
    name = product.name if product else str(fallback.get("name") or "—")
    barcode = product.barcode_display() if product else str(fallback.get("barcode") or "—")
    thumbnail_url = product.thumbnail_url if product and product.thumbnail_url else fallback.get("thumbnail_url")
    profit_markup = None
    profit_markup_negative = False
    if product:
        from app.services.product_profit import scheme_profit_markup, scheme_profit_markup_line

        fbo_data = scheme_profit_markup(product, "fbo")
        fbo_line = scheme_profit_markup_line(product, "fbo")
        if fbo_line:
            profit_markup = fbo_line
            if fbo_data:
                profit_markup_negative = (
                    fbo_data["profit_min"] < 0
                    or fbo_data["profit_max"] < 0
                    or fbo_data["markup_min"] < 0
                    or fbo_data["markup_max"] < 0
                )
    return {
        "offer_id": offer_id or "—",
        "name": name,
        "barcode": barcode,
        "thumbnail_url": thumbnail_url,
        "profit_markup": profit_markup,
        "profit_markup_negative": profit_markup_negative,
    }


def _shipments_in_range(user_id: int, warehouse_name: str, start, end) -> list[Shipment]:
    shipments = (
        Shipment.query.filter(
            Shipment.user_id == user_id,
            Shipment.supply_date >= start,
            Shipment.supply_date <= end,
        )
        .order_by(Shipment.supply_date.asc())
        .all()
    )
    result = []
    for shipment in shipments:
        if shipment.status not in SUPPLY_RECEIVED_STATUSES:
            continue
        if not warehouse_names_match(shipment.warehouse_name, warehouse_name):
            continue
        result.append(shipment)
    return result


def _bundle_ids(shipment: Shipment) -> list[str]:
    raw = shipment.raw_data if isinstance(shipment.raw_data, dict) else {}
    supplies = raw.get("supplies") or []
    bundle_ids: list[str] = []
    for supply in supplies:
        if not isinstance(supply, dict):
            continue
        bundle_id = supply.get("bundle_id")
        if bundle_id and str(bundle_id) not in bundle_ids:
            bundle_ids.append(str(bundle_id))
    return bundle_ids


def _aggregate_incoming(
    user,
    warehouse_name: str,
    date_from: date,
    date_to: date,
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    start, end = utc_bounds_for_local_dates(date_from, date_to)
    shipments = _shipments_in_range(user.id, warehouse_name, start, end)
    totals: dict[str, int] = defaultdict(int)
    meta: dict[str, dict[str, Any]] = {}

    bundle_cache: dict[str, list[dict]] = {}
    for shipment in shipments:
        for bundle_id in _bundle_ids(shipment):
            if bundle_id not in bundle_cache and user.has_ozon_credentials():
                bundle_cache[bundle_id] = fetch_bundle_items(
                    user.ozon_client_id,
                    user.ozon_api_key,
                    bundle_id,
                )
            for item in bundle_cache.get(bundle_id, []):
                if not isinstance(item, dict):
                    continue
                qty = int(item.get("quantity") or 0)
                if qty <= 0:
                    continue
                key = _product_key(item.get("offer_id"), item.get("sku"))
                totals[key] += qty
                meta[key] = {
                    "offer_id": str(item.get("offer_id") or "—"),
                    "name": str(item.get("name") or "—"),
                    "barcode": str(item.get("barcode") or "—"),
                    "thumbnail_url": item.get("icon_path"),
                }
    return totals, meta


def _aggregate_fbo_orders(
    user_id: int,
    date_from: date,
    date_to: date,
    warehouse_name: str | None = None,
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    from app.models import Order

    start, end = utc_bounds_for_local_dates(date_from, date_to)
    orders = (
        Order.query.filter(
            Order.user_id == user_id,
            Order.scheme == "FBO",
            Order.status == ORDER_STATUS_DELIVERED,
            Order.order_date >= start,
            Order.order_date <= end,
        )
        .all()
    )
    totals: dict[str, int] = defaultdict(int)
    meta: dict[str, dict[str, Any]] = {}

    for order in orders:
        raw = order.raw_data if isinstance(order.raw_data, dict) else {}
        if warehouse_name:
            analytics = raw.get("analytics_data") if isinstance(raw.get("analytics_data"), dict) else {}
            if not warehouse_names_match(analytics.get("warehouse_name"), warehouse_name):
                continue
        for item in raw.get("products") or []:
            if not isinstance(item, dict):
                continue
            qty = int(item.get("quantity") or 1)
            if qty <= 0:
                continue
            key = _product_key(item.get("offer_id"), item.get("sku"))
            totals[key] += qty
            meta[key] = {
                "offer_id": str(item.get("offer_id") or "—"),
                "name": str(item.get("name") or "—"),
            }
    return totals, meta


def _aggregate_outgoing(
    user_id: int,
    warehouse_name: str,
    date_from: date,
    date_to: date,
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    return _aggregate_fbo_orders(user_id, date_from, date_to, warehouse_name=warehouse_name)


def _aggregate_fbo_stock_all_warehouses(
    stock_rows: list[dict],
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    totals: dict[str, int] = defaultdict(int)
    meta: dict[str, dict[str, Any]] = {}
    for row in stock_rows:
        free_qty = int(row.get("free_to_sell_amount") or 0)
        reserved = int(row.get("reserved_amount") or 0)
        promised = int(row.get("promised_amount") or 0)
        qty = free_qty + reserved + promised
        if qty <= 0:
            continue
        key = _product_key(row.get("item_code"), row.get("sku"))
        totals[key] += qty
        meta[key] = {
            "offer_id": str(row.get("item_code") or "—"),
            "name": str(row.get("item_name") or "—"),
        }
    return totals, meta


def _current_stock_map(rows: list[dict], warehouse_name: str) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    totals: dict[str, int] = defaultdict(int)
    meta: dict[str, dict[str, Any]] = {}
    for item in _warehouse_stock_rows(rows, warehouse_name):
        key = _product_key(item.get("offer_id"), item.get("sku"))
        totals[key] += int(item.get("quantity") or 0)
        meta[key] = {
            "offer_id": item.get("offer_id") or "—",
            "name": item.get("name") or "—",
        }
    return totals, meta


def build_supply_planning_report(
    user,
    warehouse_name: str,
    date_from: date,
    date_to: date,
) -> dict:
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле."}
    if not warehouse_name:
        return {"ok": False, "error": "Выберите склад."}
    if date_from > date_to:
        return {"ok": False, "error": "Дата начала не может быть позже даты окончания."}
    if (date_to - date_from).days > 365:
        return {"ok": False, "error": "Максимальный период — 365 дней."}

    sync_to = max(date_to, local_today())
    try:
        load_supplies_from_ozon(user, date_from, sync_to)
    except Exception as exc:
        return {"ok": False, "error": f"Не удалось загрузить поставки: {exc}"}

    try:
        stock_rows = get_stock_report_cache(user.id)
        if stock_rows is None:
            stock_rows = fetch_stock_rows(user.ozon_client_id, user.ozon_api_key)
    except Exception as exc:
        return {"ok": False, "error": f"Не удалось загрузить остатки: {exc}"}

    incoming, incoming_meta = _aggregate_incoming(user, warehouse_name, date_from, date_to)
    outgoing, outgoing_meta = _aggregate_outgoing(user.id, warehouse_name, date_from, date_to)
    fbo_orders_all, fbo_orders_meta = _aggregate_fbo_orders(user.id, date_from, date_to)
    fbo_stock_all, fbo_stock_meta = _aggregate_fbo_stock_all_warehouses(stock_rows)
    current_stock, stock_meta = _current_stock_map(stock_rows, warehouse_name)

    today = local_today()
    closing_stock = dict(current_stock)
    if date_to < today:
        after_from = date_to + timedelta(days=1)
        incoming_after, _ = _aggregate_incoming(user, warehouse_name, after_from, today)
        outgoing_after, _ = _aggregate_outgoing(user.id, warehouse_name, after_from, today)
        for key, qty in incoming_after.items():
            closing_stock[key] = closing_stock.get(key, 0) - qty
        for key, qty in outgoing_after.items():
            closing_stock[key] = closing_stock.get(key, 0) + qty

    all_keys = (
        set(fbo_stock_all)
        | set(fbo_orders_all)
        | set(current_stock)
        | set(incoming)
        | set(outgoing)
        | set(closing_stock)
    )
    catalog = _catalog_lookup(user.id)
    rows: list[dict] = []

    for key in all_keys:
        incoming_qty = int(incoming.get(key, 0))
        outgoing_qty = int(outgoing.get(key, 0))
        closing_qty = int(closing_stock.get(key, 0))
        opening_qty = closing_qty - incoming_qty + outgoing_qty
        fbo_orders_qty = int(fbo_orders_all.get(key, 0))
        fbo_stock_qty = int(fbo_stock_all.get(key, 0))
        if not any((
            opening_qty,
            incoming_qty,
            outgoing_qty,
            closing_qty,
            fbo_orders_qty,
            fbo_stock_qty,
        )):
            continue

        fallback = (
            incoming_meta.get(key)
            or outgoing_meta.get(key)
            or stock_meta.get(key)
            or fbo_stock_meta.get(key)
            or fbo_orders_meta.get(key)
            or {}
        )
        product = _resolve_product_meta(key, catalog=catalog, fallback=fallback)
        rows.append(
            {
                **product,
                "opening": opening_qty,
                "incoming": incoming_qty,
                "outgoing": outgoing_qty,
                "closing": closing_qty,
                "fbo_orders": fbo_orders_qty,
                "fbo_stock": fbo_stock_qty,
            }
        )

    rows.sort(key=lambda row: (str(row.get("name") or "").lower(), str(row.get("offer_id") or "")))

    return {
        "ok": True,
        "warehouse_name": warehouse_name,
        "date_from": date_from,
        "date_to": date_to,
        "rows": rows,
        "summary": {
            "sku_count": len(rows),
            "opening": sum(row["opening"] for row in rows),
            "incoming": sum(row["incoming"] for row in rows),
            "outgoing": sum(row["outgoing"] for row in rows),
            "closing": sum(row["closing"] for row in rows),
            "fbo_orders": sum(fbo_orders_all.values()),
            "fbo_stock": sum(fbo_stock_all.values()),
        },
    }


def list_warehouses_with_stock(user) -> list[dict]:
    rows = get_stock_report_cache(user.id)
    if rows is None and user.has_ozon_credentials():
        try:
            rows = fetch_stock_rows(user.ozon_client_id, user.ozon_api_key)
        except Exception:
            rows = None

    if not rows:
        return []

    from app.ozon.stocks import group_warehouses

    return group_warehouses(rows)
