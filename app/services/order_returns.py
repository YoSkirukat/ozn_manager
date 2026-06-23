"""Связь заказов с возвратами после доставки."""

from __future__ import annotations

import re

from app.models import ORDER_STATUS_DELIVERED, Order

_RFBS_RETURN_NUMBER_RE = re.compile(r"^(\d+)-R\d+$", re.IGNORECASE)


def is_post_delivery_return(item: dict) -> bool:
    """Возврат после доставки: тип «Возврат» и товар получен продавцом."""
    if str(item.get("application_type") or "").strip() != "Возврат":
        return False
    return str(item.get("status_tone") or "").strip() == "received"


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


def order_has_post_delivery_return(order, postings: set[str] | None = None) -> bool:
    if getattr(order, "_has_post_delivery_return", None) is not None:
        return bool(order._has_post_delivery_return)

    if order.status != ORDER_STATUS_DELIVERED:
        return False

    if postings is None:
        postings = build_post_delivery_return_postings(order.user_id)

    return order.ozon_order_id in postings


def attach_post_delivery_return_flags(orders: list, user_id: int) -> None:
    if not orders:
        return

    postings = build_post_delivery_return_postings(user_id)
    for order in orders:
        order._has_post_delivery_return = (
            order.status == ORDER_STATUS_DELIVERED and order.ozon_order_id in postings
        )
