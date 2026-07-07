"""Связь заказов с возвратами после доставки."""

from __future__ import annotations

import re
from decimal import Decimal

from app.models import ORDER_STATUS_DELIVERED, Order

_RFBS_RETURN_NUMBER_RE = re.compile(r"^(\d+)-R\d+$", re.IGNORECASE)
FINANCIAL_REFUND_RAW_CACHE_KEY = "_financial_refund"


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal(0)


def is_post_delivery_return(item: dict) -> bool:
    """Возврат после доставки: тип «Возврат» и товар получен продавцом."""
    if str(item.get("application_type") or "").strip() != "Возврат":
        return False
    return str(item.get("status_tone") or "").strip() == "received"


def accruals_have_revenue_reversal(accruals: list | None) -> bool:
    """Сторно выручки в кэше начислений (отрицательная строка «Выручка»)."""
    if not accruals:
        return False
    for row in accruals:
        if not isinstance(row, dict):
            continue
        if row.get("type") == "group":
            for item in row.get("items") or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("label") or "") == "Выручка" and item.get("negative"):
                    return True
        elif str(row.get("label") or "") == "Выручка" and row.get("negative"):
            return True
    return False


def operations_have_revenue_reversal(operations: list | None) -> bool:
    from app.ozon.finance import is_acquiring_operation

    if not operations:
        return False
    for op in operations:
        if not isinstance(op, dict) or is_acquiring_operation(op):
            continue
        if _decimal(op.get("accruals_for_sale")) < 0:
            return True
    return False


def detect_financial_refund(
    *,
    accruals: list | None = None,
    operations: list | None = None,
    total_accrued=None,
) -> bool:
    if accruals_have_revenue_reversal(accruals):
        return True
    if operations_have_revenue_reversal(operations):
        return True
    if total_accrued is not None and _decimal(total_accrued) < 0:
        return True
    return False


def _posting_from_return_item(item: dict, user_id: int | None = None) -> str | None:
    posting = str(item.get("posting_number") or "").strip()
    if posting:
        return posting

    application_number = str(item.get("application_number") or "").strip()
    match = _RFBS_RETURN_NUMBER_RE.match(application_number)
    if not match or not user_id:
        return None

    prefix = match.group(1)
    candidates = (
        Order.query.filter(
            Order.user_id == user_id,
            Order.status == ORDER_STATUS_DELIVERED,
            Order.ozon_order_id.like(f"{prefix}-%"),
        )
        .with_entities(Order.ozon_order_id)
        .all()
    )
    if len(candidates) != 1:
        return None
    return str(candidates[0][0] or "").strip() or None


def build_post_delivery_return_postings(user_id: int) -> set[str]:
    from app.services.returns_report import get_returns_report_cache

    cache = get_returns_report_cache(user_id)
    if not cache:
        return set()

    postings: set[str] = set()
    for item in cache.get("returns") or []:
        if not isinstance(item, dict) or not is_post_delivery_return(item):
            continue
        posting = _posting_from_return_item(item, user_id=user_id)
        if posting:
            postings.add(posting)
    return postings


def order_has_return_report_match(order, postings: set[str] | None = None) -> bool:
    if order.status != ORDER_STATUS_DELIVERED:
        return False
    if postings is None:
        postings = build_post_delivery_return_postings(order.user_id)
    return order.ozon_order_id in postings


def order_has_financial_refund(order, operations: list | None = None) -> bool:
    if getattr(order, "_has_financial_refund", None) is not None:
        return bool(order._has_financial_refund)

    if order.status != ORDER_STATUS_DELIVERED:
        return False

    raw = order.raw_data if isinstance(order.raw_data, dict) else {}
    if raw.get(FINANCIAL_REFUND_RAW_CACHE_KEY):
        return True

    if accruals_have_revenue_reversal(raw.get("_accruals")):
        return True

    from app.services.order_details import _financial_cache_usable

    if _financial_cache_usable(raw):
        total = raw.get("_total_accrued")
        if total is not None and _decimal(total) < 0:
            return True

    return operations_have_revenue_reversal(operations)


def order_has_post_delivery_return(order, postings: set[str] | None = None) -> bool:
    if getattr(order, "_has_post_delivery_return", None) is not None:
        return bool(order._has_post_delivery_return)

    return order_has_refund_after_delivery(order, postings=postings)


def order_has_refund_after_delivery(order, postings: set[str] | None = None) -> bool:
    return order_has_return_report_match(order, postings=postings) or order_has_financial_refund(order)


def persist_financial_refund_cache(order, refund: bool) -> None:
    raw = order.raw_data if isinstance(order.raw_data, dict) else {}
    normalized = bool(refund)
    if raw.get(FINANCIAL_REFUND_RAW_CACHE_KEY) == normalized:
        return
    order.raw_data = {**raw, FINANCIAL_REFUND_RAW_CACHE_KEY: normalized}


def attach_post_delivery_return_flags(orders: list, user_id: int) -> None:
    if not orders:
        return

    postings = build_post_delivery_return_postings(user_id)
    for order in orders:
        has_report = order_has_return_report_match(order, postings=postings)
        has_financial = order_has_financial_refund(order)
        order._has_financial_refund = has_financial
        order._has_post_delivery_return = has_report or has_financial


def refund_after_delivery_tooltip(order) -> str:
    has_report = order_has_return_report_match(order)
    has_financial = order_has_financial_refund(order)
    if has_report and has_financial:
        return "Возврат товара и сторно начислений после доставки"
    if has_report:
        return "Возврат товара после доставки"
    if has_financial:
        return "Возврат средств: Ozon оформил сторно начислений, статус остаётся «Доставлен»"
    return "Возврат после доставки"
