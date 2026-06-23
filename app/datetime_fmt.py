"""Отображение дат/времени в часовом поясе пользователя (по умолчанию Москва)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Europe/Moscow"


def get_app_timezone_name() -> str:
    try:
        from flask import current_app

        return current_app.config.get("APP_TIMEZONE", DEFAULT_TIMEZONE)
    except RuntimeError:
        return DEFAULT_TIMEZONE


def get_app_timezone() -> ZoneInfo:
    return ZoneInfo(get_app_timezone_name())


def to_local(dt: datetime | None, tz_name: str | None = None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    tz = ZoneInfo(tz_name) if tz_name else get_app_timezone()
    return dt.astimezone(tz)


def local_today(tz_name: str | None = None) -> date:
    tz = ZoneInfo(tz_name) if tz_name else get_app_timezone()
    return datetime.now(tz).date()


def local_calendar_date(dt: datetime | None, tz_name: str | None = None) -> date | None:
    local = to_local(dt, tz_name)
    return local.date() if local else None


def utc_bounds_for_local_dates(
    date_from: date,
    date_to: date,
    tz_name: str | None = None,
) -> tuple[datetime, datetime]:
    """Границы периода в UTC для фильтра по календарным датам в локальном поясе."""
    tz = ZoneInfo(tz_name) if tz_name else get_app_timezone()
    start_local = datetime.combine(date_from, time.min, tzinfo=tz)
    end_local = datetime.combine(date_to, time.max.replace(microsecond=999999), tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def format_datetime(dt: datetime | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    local = to_local(dt)
    if local is None:
        return "—"
    return local.strftime(fmt)


def to_iso_utc(dt: datetime | None) -> str | None:
    """ISO-строка в UTC для JSON (SQLite часто отдаёт naive datetime)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def format_date(dt: datetime | date | None, fmt: str = "%d.%m.%Y") -> str:
    if dt is None:
        return "—"
    if isinstance(dt, datetime):
        local = to_local(dt)
        return local.strftime(fmt) if local else "—"
    return dt.strftime(fmt)


RU_MONTH_SHORT = (
    "янв",
    "фев",
    "мар",
    "апр",
    "май",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
)


def format_return_status_date(dt: datetime | None) -> str:
    local = to_local(dt)
    if local is None:
        return "—"
    month = RU_MONTH_SHORT[local.month - 1]
    return f"{local.day} {month}"
