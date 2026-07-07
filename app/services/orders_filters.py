"""Фильтры списка заказов (статус, схема, доставка) в сессии и query-параметрах."""

from flask import request, session

from app.models import ORDER_STATUS_LABELS, Order

SESSION_ORDERS_FILTERS = "orders_filters"
VALID_SCHEMES = frozenset({Order.SCHEME_FBS, Order.SCHEME_FBO})
VALID_DELIVERY = frozenset({"local", "international"})


def status_options() -> list[tuple[str, str]]:
    return sorted(ORDER_STATUS_LABELS.items(), key=lambda item: item[1])


def scheme_options() -> list[tuple[str, str]]:
    return [(Order.SCHEME_FBS, "FBS"), (Order.SCHEME_FBO, "FBO")]


def delivery_options() -> list[tuple[str, str]]:
    return [
        ("local", "Локальные"),
        ("international", "Международные"),
    ]


def _parse_csv_param(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _normalize_statuses(values: list[str]) -> list[str]:
    allowed = set(ORDER_STATUS_LABELS)
    seen: list[str] = []
    for value in values:
        if value in allowed and value not in seen:
            seen.append(value)
    return seen


def _normalize_schemes(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        upper = value.upper()
        if upper in VALID_SCHEMES and upper not in seen:
            seen.append(upper)
    return seen


def _normalize_delivery(value: str | None) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_DELIVERY else ""


def get_orders_filters_from_session() -> tuple[list[str], list[str], str]:
    raw = session.get(SESSION_ORDERS_FILTERS) or {}
    statuses = _normalize_statuses(list(raw.get("status") or []))
    schemes = _normalize_schemes(list(raw.get("scheme") or []))
    delivery = _normalize_delivery(raw.get("delivery"))
    return statuses, schemes, delivery


def save_orders_filters(
    statuses: list[str],
    schemes: list[str],
    delivery: str = "",
) -> None:
    session[SESSION_ORDERS_FILTERS] = {
        "status": statuses,
        "scheme": schemes,
        "delivery": _normalize_delivery(delivery),
    }


def resolve_orders_filters() -> tuple[list[str], list[str], str]:
    """Параметры из URL (в т.ч. пустые status=/scheme=) или из сессии."""
    if "status" in request.args or "scheme" in request.args or "delivery" in request.args:
        statuses = _normalize_statuses(_parse_csv_param(request.args.get("status")))
        schemes = _normalize_schemes(_parse_csv_param(request.args.get("scheme")))
        delivery = _normalize_delivery(request.args.get("delivery"))
        save_orders_filters(statuses, schemes, delivery)
        return statuses, schemes, delivery
    return get_orders_filters_from_session()


def apply_delivery_filter(orders: list, delivery: str) -> list:
    if not delivery:
        return orders
    if delivery == "local":
        return [order for order in orders if not order.is_international()]
    if delivery == "international":
        return [order for order in orders if order.is_international()]
    return orders
