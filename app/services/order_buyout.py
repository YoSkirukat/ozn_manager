"""Выкупы маркетплейса для международных заказов и расчёт маржи."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from app.datetime_fmt import local_today
from app.ozon.buyout import fetch_buyout_products_range
from app.ozon.finance import related_posting_numbers

BUYOUT_RAW_CACHE_KEYS = ("_buyout_amount", "_buyout_products")


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal(0)


def _money(value) -> float:
    return float(_decimal(value).quantize(Decimal("0.01")))


def _order_calendar_date(order_date) -> date | None:
    if order_date is None:
        return None
    if isinstance(order_date, date) and not hasattr(order_date, "hour"):
        return order_date
    if hasattr(order_date, "date"):
        return order_date.date()
    return None


def _serialize_buyout_rows(rows: list[dict]) -> list[dict]:
    serialized: list[dict] = []
    for row in rows:
        serialized.append(
            {
                "posting_number": str(row.get("posting_number") or ""),
                "offer_id": str(row.get("offer_id") or ""),
                "sku": str(row.get("sku") or ""),
                "quantity": int(row.get("quantity") or 0),
                "amount": _money(row.get("amount")),
                "buyout_price": _money(row.get("buyout_price")) if row.get("buyout_price") is not None else None,
            }
        )
    return serialized


def build_buyout_index(products: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = defaultdict(list)
    for row in products:
        posting_number = str(row.get("posting_number") or "").strip()
        if posting_number:
            index[posting_number].append(row)
    return dict(index)


def _orders_date_bounds(orders: list) -> tuple[date, date] | None:
    dates: list[date] = []
    for order in orders:
        order_date = _order_calendar_date(getattr(order, "order_date", None))
        if order_date:
            dates.append(order_date)
    if not dates:
        return None
    return min(dates), max(dates)


def build_buyout_index_for_orders(user, orders: list) -> dict[str, list[dict]]:
    if not user or not user.has_ozon_credentials():
        return {}

    international = [
        order
        for order in orders
        if getattr(order, "status", None) == "delivered" and order.is_international()
    ]
    if not international:
        return {}

    bounds = _orders_date_bounds(international)
    if not bounds:
        return {}

    date_from, date_to = bounds
    today = local_today()
    if date_to > today:
        date_to = today
    # Небольшой запас: выкуп может попасть в отчёт чуть позже даты заказа.
    date_to = min(date_to + timedelta(days=14), today)

    try:
        products = fetch_buyout_products_range(
            user.ozon_client_id,
            user.ozon_api_key,
            date_from,
            date_to,
        )
    except Exception:
        return {}

    return build_buyout_index(products)


def resolve_order_buyout_rows(order, buyout_index: dict[str, list[dict]] | None) -> list[dict]:
    if not buyout_index:
        return []

    posting_number = str(getattr(order, "ozon_order_id", "") or "").strip()
    if not posting_number:
        return []

    rows: list[dict] = []
    seen: set[tuple] = set()
    for number in related_posting_numbers(posting_number):
        for row in buyout_index.get(number, []):
            key = (
                number,
                str(row.get("offer_id") or ""),
                str(row.get("sku") or ""),
                _money(row.get("amount")),
                int(row.get("quantity") or 0),
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def _match_buyout_row(product: dict, candidates: list[dict]) -> dict | None:
    offer_id = str(product.get("offer_id") or "").strip()
    if offer_id and offer_id != "—":
        for index, row in enumerate(candidates):
            if str(row.get("offer_id") or "").strip() == offer_id:
                return candidates.pop(index)

    barcode = str(product.get("barcode") or "").strip()
    if barcode and barcode != "—":
        for index, row in enumerate(candidates):
            if str(row.get("sku") or "").strip() == barcode:
                return candidates.pop(index)

    return None


def attach_buyout_amounts(products: list[dict], buyout_rows: list[dict]) -> float:
    """Проставляет buyout_amount в строки товаров, возвращает сумму начислений."""
    remaining = [dict(row) for row in buyout_rows]
    total = Decimal(0)

    if len(products) == 1 and len(remaining) == 1:
        amount = _decimal(remaining[0].get("amount"))
        products[0]["buyout_amount"] = _money(amount) if amount > 0 else None
        return _money(amount)

    for product in products:
        matched = _match_buyout_row(product, remaining)
        if not matched:
            product["buyout_amount"] = None
            continue
        amount = _decimal(matched.get("amount"))
        product["buyout_amount"] = _money(amount) if amount > 0 else None
        total += amount

    if total <= 0 and len(remaining) == 1 and len(products) == 1:
        amount = _decimal(remaining[0].get("amount"))
        products[0]["buyout_amount"] = _money(amount) if amount > 0 else None
        total = amount

    if total <= 0 and buyout_rows:
        total = sum(_decimal(row.get("amount")) for row in buyout_rows)

    return _money(total)


def _cached_buyout_amount(raw: dict | None) -> float | None:
    if not isinstance(raw, dict):
        return None
    value = raw.get("_buyout_amount")
    if value is None:
        return None
    try:
        return _money(value)
    except (TypeError, ValueError):
        return None


def _cached_buyout_products(raw: dict | None) -> list[dict]:
    if not isinstance(raw, dict):
        return []
    rows = raw.get("_buyout_products")
    return rows if isinstance(rows, list) else []


def persist_buyout_cache(order, buyout_rows: list[dict], total_amount: float) -> None:
    raw = order.raw_data if isinstance(order.raw_data, dict) else {}
    normalized_total = _money(total_amount)
    serialized = _serialize_buyout_rows(buyout_rows)
    if (
        _cached_buyout_amount(raw) == normalized_total
        and _cached_buyout_products(raw) == serialized
    ):
        return
    order.raw_data = {
        **raw,
        "_buyout_amount": normalized_total,
        "_buyout_products": serialized,
    }


def clear_buyout_cache(order) -> None:
    raw = order.raw_data if isinstance(order.raw_data, dict) else {}
    if not any(key in raw for key in BUYOUT_RAW_CACHE_KEYS):
        return
    order.raw_data = {key: value for key, value in raw.items() if key not in BUYOUT_RAW_CACHE_KEYS}


def apply_buyout_to_products(
    order,
    products: list[dict],
    *,
    user=None,
    use_api: bool = True,
    buyout_index: dict[str, list[dict]] | None = None,
) -> float:
    """Возвращает сумму начислений Ozon по выкупу для заказа."""
    raw = order.raw_data if isinstance(order.raw_data, dict) else {}

    if not use_api:
        cached_rows = _cached_buyout_products(raw)
        if cached_rows:
            return attach_buyout_amounts(products, cached_rows)
        cached_total = _cached_buyout_amount(raw)
        if cached_total is not None and len(products) == 1:
            products[0]["buyout_amount"] = cached_total
            return cached_total
        return 0.0

    buyout_rows = resolve_order_buyout_rows(order, buyout_index)
    if not buyout_rows and user and user.has_ozon_credentials() and buyout_index is None:
        order_date = _order_calendar_date(order.order_date) or local_today()
        date_from = order_date
        date_to = min(order_date + timedelta(days=30), local_today())
        try:
            fetched = fetch_buyout_products_range(
                user.ozon_client_id,
                user.ozon_api_key,
                date_from,
                date_to,
            )
        except Exception:
            fetched = []
        single_index = build_buyout_index(fetched)
        buyout_rows = resolve_order_buyout_rows(order, single_index)

    total_amount = attach_buyout_amounts(products, buyout_rows)
    if buyout_rows:
        persist_buyout_cache(order, buyout_rows, total_amount)
    return total_amount
