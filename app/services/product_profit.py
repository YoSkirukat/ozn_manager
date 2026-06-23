"""Прибыль и наценка по схемам FBO/FBS."""

from __future__ import annotations

from decimal import Decimal

from app.money_fmt import format_money_ru
from app.services.product_commissions import _enrich_commission_block

SCHEME_ORDER = ("fbs", "fbo")
SCHEME_LABELS = {"fbs": "FBS", "fbo": "FBO"}


def _sale_price(product) -> Decimal:
    return Decimal(str(product.effective_sale_price()))


def _commission_bounds(product, scheme: str) -> tuple[float | None, float | None]:
    if not isinstance(product.commission_details, dict):
        return None, None
    block = product.commission_details.get(scheme)
    if not isinstance(block, dict) or not block.get("has_data"):
        return None, None

    enriched = _enrich_commission_block(block, float(_sale_price(product)))
    return enriched.get("total_min"), enriched.get("total_max")


def scheme_profit_markup(product, scheme: str) -> dict | None:
    """Прибыль и наценка для одной схемы (с учётом диапазона комиссии)."""
    if product.purchase_price is None:
        return None
    comm_min, comm_max = _commission_bounds(product, scheme)
    if comm_min is None and comm_max is None:
        return None

    sale = _sale_price(product)
    purchase = Decimal(str(product.purchase_price))
    cmin = Decimal(str(comm_min or 0))
    cmax = Decimal(str(comm_max if comm_max is not None else comm_min))

    profit_min = sale - purchase - cmax
    profit_max = sale - purchase - cmin

    if purchase <= 0:
        markup_min = markup_max = Decimal(0)
    else:
        markup_min = (profit_min / purchase) * Decimal(100)
        markup_max = (profit_max / purchase) * Decimal(100)

    return {
        "profit_min": float(profit_min.quantize(Decimal("0.01"))),
        "profit_max": float(profit_max.quantize(Decimal("0.01"))),
        "markup_min": float(markup_min.quantize(Decimal("0.01"))),
        "markup_max": float(markup_max.quantize(Decimal("0.01"))),
    }


def _format_range_value(min_val: float, max_val: float, *, formatter) -> str:
    if abs(min_val - max_val) < 0.005:
        return formatter(max_val)
    return f"{formatter(min_val)} – {formatter(max_val)}"


def format_percent_ru(value: float) -> str:
    text = f"{value:.2f}".replace(".", ",")
    return f"{text}%"


def scheme_profit_markup_line(product, scheme: str) -> str | None:
    """Одна строка: «5 763.49 ₽ – 5 945.49 ₽ (22,78% – 23,50%)»."""
    data = scheme_profit_markup(product, scheme)
    if not data:
        return None
    profit = _format_range_value(
        data["profit_min"],
        data["profit_max"],
        formatter=lambda v: f"{format_money_ru(v)} ₽",
    )
    markup = _format_range_value(
        data["markup_min"],
        data["markup_max"],
        formatter=format_percent_ru,
    )
    return f"{profit} ({markup})"


def _scheme_profit_markup_negative(data: dict) -> bool:
    return (
        data["profit_min"] < 0
        or data["profit_max"] < 0
        or data["markup_min"] < 0
        or data["markup_max"] < 0
    )


def profit_markup_scheme_rows(product) -> list[tuple[str, str, bool]]:
    """Строки для ячейки: [(«FBS», текст, отрицательная), («FBO», текст, отрицательная)]."""
    if product.purchase_price is None:
        return []
    rows: list[tuple[str, str, bool]] = []
    for scheme in SCHEME_ORDER:
        data = scheme_profit_markup(product, scheme)
        line = scheme_profit_markup_line(product, scheme)
        if line and data:
            rows.append((SCHEME_LABELS[scheme], line, _scheme_profit_markup_negative(data)))
    return rows

