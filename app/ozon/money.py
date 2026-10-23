"""Денежные значения Ozon: число, строка или объект `{"amount": ..., "currency": ...}`."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def money_amount(value) -> Decimal:
    """Сумма из денежного поля Ozon.

    Ozon отдаёт деньги по-разному: `1705`, `"1705"`, `{"amount": "1705", "currency": "RUB"}`.
    Неизвестный формат не должен ломать отчёты, поэтому возвращаем ноль.
    """
    if isinstance(value, dict):
        value = value.get("amount")
    if value is None or value == "":
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


def money_currency(value) -> str:
    """Код валюты денежного поля Ozon (пустая строка, если его нет)."""
    if isinstance(value, dict):
        return str(value.get("currency") or "").strip().upper()
    return ""
