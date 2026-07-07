"""Отчёт о выкупленных товарах Ozon (/v1/finance/products/buyout)."""

from __future__ import annotations

from datetime import date, timedelta

from app.ozon.client import _post

MAX_BUYOUT_PERIOD_DAYS = 31


def iter_buyout_windows(date_from: date, date_to: date):
    """Разбивает период на окна не длиннее 31 дня (лимит API)."""
    if date_from > date_to:
        return
    current = date_from
    while current <= date_to:
        end = min(current + timedelta(days=MAX_BUYOUT_PERIOD_DAYS - 1), date_to)
        yield current, end
        current = end + timedelta(days=1)


def fetch_buyout_products(
    client_id: str,
    api_key: str,
    date_from: date,
    date_to: date,
) -> list[dict]:
    if date_from > date_to:
        return []
    if (date_to - date_from).days >= MAX_BUYOUT_PERIOD_DAYS:
        raise ValueError(f"Период отчёта о выкупах не может превышать {MAX_BUYOUT_PERIOD_DAYS} дней.")

    data = _post(
        client_id,
        api_key,
        "/v1/finance/products/buyout",
        {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        },
    )
    products = data.get("products") or []
    return [row for row in products if isinstance(row, dict)]


def fetch_buyout_products_range(
    client_id: str,
    api_key: str,
    date_from: date,
    date_to: date,
) -> list[dict]:
    """Загружает выкупы за период, при необходимости разбивая на окна по 31 день."""
    rows: list[dict] = []
    for window_from, window_to in iter_buyout_windows(date_from, date_to):
        rows.extend(fetch_buyout_products(client_id, api_key, window_from, window_to))
    return rows
