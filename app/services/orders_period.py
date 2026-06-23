"""Сохранение последнего периода списков в сессии пользователя."""

from datetime import date, datetime, timedelta

from flask import session

SESSION_ORDERS_PERIOD = "orders_period"
SESSION_SHIPMENTS_PERIOD = "shipments_period"
DEFAULT_SHIPMENTS_DAYS = 21


def _parse_date_param(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def format_period_range(date_from: date, date_to: date) -> str:
    return f"с {date_from.strftime('%d.%m.%Y')} по {date_to.strftime('%d.%m.%Y')}"


def get_orders_period() -> tuple[date | None, date | None]:
    raw = session.get(SESSION_ORDERS_PERIOD) or {}
    return _parse_date_param(raw.get("from")), _parse_date_param(raw.get("to"))


def save_orders_period(date_from: date, date_to: date) -> None:
    session[SESSION_ORDERS_PERIOD] = {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
    }


def get_shipments_period() -> tuple[date | None, date | None]:
    raw = session.get(SESSION_SHIPMENTS_PERIOD) or {}
    return _parse_date_param(raw.get("from")), _parse_date_param(raw.get("to"))


def save_shipments_period(date_from: date, date_to: date) -> None:
    session[SESSION_SHIPMENTS_PERIOD] = {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
    }


def default_shipments_period() -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=DEFAULT_SHIPMENTS_DAYS - 1), today


def resolve_orders_period() -> tuple[date, date]:
    from app.services.orders_chart import default_chart_period

    date_from, date_to = get_orders_period()
    if date_from and date_to:
        return date_from, date_to
    return default_chart_period()


def resolve_shipments_period() -> tuple[date, date]:
    date_from, date_to = get_shipments_period()
    if date_from and date_to:
        return date_from, date_to
    return default_shipments_period()
