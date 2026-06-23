"""Сводки по заказам для дашборда: склады и топ товаров."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.datetime_fmt import local_calendar_date, utc_bounds_for_local_dates
from app.models import Order, Product
from app.ozon.stocks import group_products, product_row_key
from app.services.stock_report import get_stock_report_cache
from app.services.supply_planning import _product_key

TOP_PRODUCTS_LIMIT = 10


def _order_source_name(raw: dict) -> str:
    analytics = raw.get("analytics_data")
    if isinstance(analytics, dict):
        name = str(analytics.get("warehouse_name") or "").strip()
        if name:
            return name

    financial = raw.get("financial_data")
    if isinstance(financial, dict):
        for key in ("cluster_from", "cluster_to"):
            name = str(financial.get(key) or "").strip()
            if name:
                return name

    return "Не указан"


def _orders_in_period(user_id: int, date_from: date, date_to: date) -> list[Order]:
    start, end = utc_bounds_for_local_dates(date_from, date_to)
    return (
        Order.query.filter(
            Order.user_id == user_id,
            Order.order_date >= start,
            Order.order_date <= end,
        )
        .all()
    )


def _stock_totals_map(user_id: int) -> dict[str, int]:
    rows = get_stock_report_cache(user_id)
    if not rows:
        return {}
    totals: dict[str, int] = {}
    for item in group_products(rows):
        key = item.get("product_key") or product_row_key(item)
        if key:
            totals[key] = int(item.get("total_quantity") or 0)
    return totals


def _lookup_stock(stock_map: dict[str, int], offer_id: str | None, sku: str | None) -> int:
    offer = str(offer_id or "").strip()
    if offer and offer != "—":
        qty = stock_map.get(f"offer:{offer}")
        if qty is not None:
            return qty
    sku_text = str(sku or "").strip()
    if sku_text:
        qty = stock_map.get(f"sku:{sku_text}")
        if qty is not None:
            return qty
    return 0


def _enrich_product_rows(user_id: int, rows: list[dict]) -> list[dict]:
    if not rows:
        return rows

    offer_ids = {str(row.get("offer_id") or "").strip() for row in rows}
    offer_ids.discard("")
    offer_ids.discard("—")

    by_offer: dict[str, Product] = {}
    if offer_ids:
        for product in Product.query.filter(
            Product.user_id == user_id,
            Product.offer_id.in_(offer_ids),
        ):
            if product.offer_id:
                by_offer[str(product.offer_id)] = product

    for row in rows:
        offer_id = str(row.get("offer_id") or "").strip()
        product = by_offer.get(offer_id) if offer_id and offer_id != "—" else None
        if product:
            if product.thumbnail_url and not row.get("thumbnail_url"):
                row["thumbnail_url"] = product.thumbnail_url
            if product.name and (not row.get("name") or row.get("name") == "—"):
                row["name"] = product.name
            if product.barcode:
                row["barcode"] = product.barcode
        row.setdefault("thumbnail_url", None)
        row.setdefault("barcode", "—")
    return rows


def build_orders_breakdown(user_id: int, date_from: date, date_to: date) -> dict:
    warehouse_totals: dict[str, int] = defaultdict(int)
    product_totals: dict[str, int] = defaultdict(int)
    product_meta: dict[str, dict] = {}

    for order in _orders_in_period(user_id, date_from, date_to):
        day = local_calendar_date(order.order_date)
        if not day or day < date_from or day > date_to:
            continue

        raw = order.raw_data if isinstance(order.raw_data, dict) else {}
        source = _order_source_name(raw)

        for item in order.products_list():
            if not isinstance(item, dict):
                continue
            qty = int(item.get("quantity") or 1)
            if qty <= 0:
                continue

            warehouse_totals[source] += qty

            key = _product_key(item.get("offer_id"), item.get("sku"))
            product_totals[key] += qty
            if key not in product_meta:
                product_meta[key] = {
                    "offer_id": str(item.get("offer_id") or "—"),
                    "sku": str(item.get("sku") or ""),
                    "name": str(item.get("name") or "—"),
                }

    warehouses = [
        {"name": name, "quantity": qty}
        for name, qty in warehouse_totals.items()
    ]
    warehouses.sort(key=lambda row: (-row["quantity"], row["name"].lower()))

    stock_map = _stock_totals_map(user_id)
    top_rows: list[dict] = []
    for key, qty in sorted(product_totals.items(), key=lambda item: (-item[1], item[0])):
        if len(top_rows) >= TOP_PRODUCTS_LIMIT:
            break
        meta = product_meta.get(key, {})
        offer_id = meta.get("offer_id")
        sku = meta.get("sku")
        top_rows.append(
            {
                "product_key": key,
                "offer_id": offer_id or "—",
                "name": meta.get("name") or "—",
                "quantity": qty,
                "stock": _lookup_stock(stock_map, offer_id, sku),
            }
        )

    top_products = _enrich_product_rows(user_id, top_rows)

    return {
        "warehouses": warehouses,
        "top_products": top_products,
    }
