"""Заказы схемы FBS в разрезе складов: новые и уже отправленные."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.datetime_fmt import utc_bounds_for_local_dates
from app.models import Order

# Заказы, которые ещё не отгружены (требуют сборки/отгрузки).
FBS_NEW_STATUSES = frozenset(
    {
        "awaiting_registration",
        "awaiting_approve",
        "awaiting_packaging",
        "awaiting_deliver",
        "awaiting_pickup",
    }
)

# Заказы, которые уже отправлены покупателю или доставлены.
FBS_SHIPPED_STATUSES = frozenset({"delivering", "delivered"})

# Отменённые и спорные заказы на странице не показываем (см. раздел «Заказы»).
FBS_BOARD_STATUSES = FBS_NEW_STATUSES | FBS_SHIPPED_STATUSES

UNKNOWN_WAREHOUSE_NAME = "Склад не указан"


def order_warehouse_name(order: Order) -> str:
    """Название склада FBS из данных отправления Ozon.

    Основной источник — `delivery_method.warehouse` (склад отправки FBS),
    запасной — `analytics_data.warehouse`.
    """
    raw = order.raw_data if isinstance(order.raw_data, dict) else {}

    for key in ("delivery_method", "analytics_data"):
        source = raw.get(key)
        if not isinstance(source, dict):
            continue
        name = str(source.get("warehouse") or source.get("warehouse_name") or "").strip()
        if name:
            return name

    for key in ("warehouse_name", "warehouse"):
        name = str(raw.get(key) or "").strip()
        if name:
            return name

    return UNKNOWN_WAREHOUSE_NAME


def order_items_quantity(order: Order) -> int:
    """Суммарное количество товаров в отправлении."""
    return order.items_quantity()


def load_fbs_orders(user_id: int, date_from: date, date_to: date) -> list[Order]:
    """Заказы FBS пользователя за период (календарные даты в часовом поясе приложения)."""
    start, end = utc_bounds_for_local_dates(date_from, date_to)
    return (
        Order.query.filter(
            Order.user_id == user_id,
            Order.scheme == Order.SCHEME_FBS,
            Order.status.in_(FBS_BOARD_STATUSES),
            Order.order_date >= start,
            Order.order_date <= end,
        )
        .order_by(Order.order_date.desc())
        .all()
    )


def _group_by_warehouse(orders: list[Order]) -> list[dict]:
    buckets: dict[str, list[Order]] = defaultdict(list)
    for order in orders:
        buckets[order_warehouse_name(order)].append(order)

    groups: list[dict] = []
    for name, items in buckets.items():
        items.sort(key=lambda order: order.order_date, reverse=True)
        groups.append(
            {
                "name": name,
                "orders": items,
                "count": len(items),
                "quantity": sum(order_items_quantity(order) for order in items),
                "total": round(sum(float(order.total or 0) for order in items), 2),
            }
        )

    groups.sort(key=lambda group: (-group["count"], group["name"].casefold()))
    return groups


def build_fbs_orders_board(
    user_id: int,
    date_from: date,
    date_to: date,
    orders: list[Order] | None = None,
) -> dict:
    """Данные страницы «Заказы FBS»: новые и отправленные, сгруппированные по складам."""
    if orders is None:
        orders = load_fbs_orders(user_id, date_from, date_to)

    new_orders = [order for order in orders if order.status in FBS_NEW_STATUSES]
    shipped_orders = [order for order in orders if order.status in FBS_SHIPPED_STATUSES]

    return {
        "orders": orders,
        "new_groups": _group_by_warehouse(new_orders),
        "shipped_groups": _group_by_warehouse(shipped_orders),
        "new_count": len(new_orders),
        "shipped_count": len(shipped_orders),
    }
