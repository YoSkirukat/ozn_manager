"""Форматирование денежных сумм для UI (ru-RU)."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_RANGE_SEPARATORS = ("–", "-", "—")


def format_money_ru(value, *, decimals: int = 2) -> str:
    """Число с пробелами в разрядах: 25295.51 → 25 295.51."""
    if value is None or value == "":
        return "—"
    try:
        amount = Decimal(str(value)).quantize(Decimal("1." + "0" * decimals))
    except (InvalidOperation, ValueError):
        return "—"

    negative = amount < 0
    amount = abs(amount)
    formatted = f"{amount:.{decimals}f}"
    int_part, frac = formatted.split(".")
    grouped = _group_int_digits(int_part)
    result = f"{grouped}.{frac}"
    return f"-{result}" if negative else result


def format_money_display_text(text: str) -> str:
    """Форматирует строку суммы или диапазона «175.00 – 190.00»."""
    raw = str(text or "").strip()
    if not raw or raw == "—":
        return "—"

    for sep in _RANGE_SEPARATORS:
        if sep in raw:
            left, right = raw.split(sep, 1)
            return f"{format_money_ru(left.strip())} – {format_money_ru(right.strip())}"

    return format_money_ru(raw)


def _group_int_digits(int_part: str) -> str:
    digits = int_part.lstrip("0") or "0"
    parts: list[str] = []
    for index, char in enumerate(reversed(digits)):
        if index and index % 3 == 0:
            parts.append(" ")
        parts.append(char)
    return "".join(reversed(parts))
