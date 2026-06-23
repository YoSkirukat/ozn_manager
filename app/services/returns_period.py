"""Период отчёта по возвратам."""

from datetime import date, timedelta

from flask import session

from app.datetime_fmt import local_today
from app.services.orders_period import _parse_date_param

SESSION_RETURNS_PERIOD = "returns_period"
DEFAULT_RETURNS_DAYS = 30


def default_returns_period() -> tuple[date, date]:
    today = local_today()
    return today - timedelta(days=DEFAULT_RETURNS_DAYS - 1), today


def get_returns_period() -> tuple[date | None, date | None]:
    raw = session.get(SESSION_RETURNS_PERIOD) or {}
    return _parse_date_param(raw.get("from")), _parse_date_param(raw.get("to"))


def save_returns_period(date_from: date, date_to: date) -> None:
    session[SESSION_RETURNS_PERIOD] = {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
    }


def resolve_returns_period() -> tuple[date, date]:
    date_from, date_to = get_returns_period()
    if date_from and date_to:
        return date_from, date_to
    return default_returns_period()
