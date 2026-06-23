"""Счётчики для карточек на дашборде."""

from __future__ import annotations

from sqlalchemy import and_, or_

from app.datetime_fmt import utc_bounds_for_local_dates
from app.models import Order, Product, Shipment, SUPPLY_ACTIVE_STATUSES
from app.services.orders_period import format_period_range, resolve_orders_period, resolve_shipments_period


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


def build_dashboard_stats(user) -> dict:
    orders_from, orders_to = resolve_orders_period()
    shipments_from, shipments_to = resolve_shipments_period()

    return {
        "products": Product.query.filter_by(user_id=user.id).count(),
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
