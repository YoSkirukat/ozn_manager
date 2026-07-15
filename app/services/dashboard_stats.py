"""Счётчики для карточек на дашборде."""

from __future__ import annotations

from sqlalchemy import and_, or_

from app.datetime_fmt import utc_bounds_for_local_dates
from app.models import Order, Shipment, SUPPLY_ACTIVE_STATUSES
from app.services.orders_period import (
    default_shipments_period,
    format_period_range,
    resolve_orders_period,
)
from app.services.returns_report import get_returns_report_cache

RETURNS_AT_PICKUP_STATUS = "В пункте выдачи"


def count_orders_in_period(user_id: int, date_from, date_to) -> int:
    start, end = utc_bounds_for_local_dates(date_from, date_to)
    return Order.query.filter(
        Order.user_id == user_id,
        Order.order_date >= start,
        Order.order_date <= end,
    ).count()


def count_shipments_in_period(user_id: int, date_from, date_to) -> int:
    start, end = utc_bounds_for_local_dates(date_from, date_to)
    return Shipment.query.filter(
        Shipment.user_id == user_id,
        or_(
            and_(
                Shipment.supply_date >= start,
                Shipment.supply_date <= end,
            ),
            Shipment.status.in_(SUPPLY_ACTIVE_STATUSES),
        ),
    ).count()


def _is_returns_at_pickup_status(status: str | None) -> bool:
    text = str(status or "").strip().lower().replace("ё", "е")
    return text in {"в пункте выдачи", "в пункте выдаче"}


def count_returns_at_pickup(user_id: int) -> int:
    cache = get_returns_report_cache(user_id)
    if not cache:
        return 0
    items = cache.get("returns")
    if not isinstance(items, list):
        return 0
    return sum(1 for item in items if _is_returns_at_pickup_status(item.get("status")))


def build_dashboard_stats(user) -> dict:
    orders_from, orders_to = resolve_orders_period()
    shipments_from, shipments_to = default_shipments_period()

    return {
        "returns_at_pickup": count_returns_at_pickup(user.id),
        "returns_at_pickup_label": RETURNS_AT_PICKUP_STATUS,
        "orders": count_orders_in_period(user.id, orders_from, orders_to),
        "orders_period": format_period_range(orders_from, orders_to),
        "orders_period_from": orders_from.isoformat(),
        "orders_period_to": orders_to.isoformat(),
        "shipments": count_shipments_in_period(user.id, shipments_from, shipments_to),
        "shipments_period": format_period_range(shipments_from, shipments_to),
        "shipments_period_from": shipments_from.isoformat(),
        "shipments_period_to": shipments_to.isoformat(),
        "products_in_promotions": user.products_in_promotions_count or 0,
    }
