"""Фильтры списка заказов (статус, схема) в сессии и query-параметрах."""

from flask import request, session

from app.models import ORDER_STATUS_LABELS, Order

SESSION_ORDERS_FILTERS = "orders_filters"
VALID_SCHEMES = frozenset({Order.SCHEME_FBS, Order.SCHEME_FBO})


def status_options() -> list[tuple[str, str]]:
    return sorted(ORDER_STATUS_LABELS.items(), key=lambda item: item[1])


def scheme_options() -> list[tuple[str, str]]:
    return [(Order.SCHEME_FBS, "FBS"), (Order.SCHEME_FBO, "FBO")]


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


def get_orders_filters_from_session() -> tuple[list[str], list[str]]:
    raw = session.get(SESSION_ORDERS_FILTERS) or {}
    statuses = _normalize_statuses(list(raw.get("status") or []))
    schemes = _normalize_schemes(list(raw.get("scheme") or []))
    return statuses, schemes


def save_orders_filters(statuses: list[str], schemes: list[str]) -> None:
    session[SESSION_ORDERS_FILTERS] = {
        "status": statuses,
        "scheme": schemes,
    }


def resolve_orders_filters() -> tuple[list[str], list[str]]:
    """Параметры из URL (в т.ч. пустые status=/scheme=) или из сессии."""
    if "status" in request.args or "scheme" in request.args:
        statuses = _normalize_statuses(_parse_csv_param(request.args.get("status")))
        schemes = _normalize_schemes(_parse_csv_param(request.args.get("scheme")))
        save_orders_filters(statuses, schemes)
        return statuses, schemes
    return get_orders_filters_from_session()
