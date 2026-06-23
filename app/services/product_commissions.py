"""Комиссии FBO/FBS для товаров."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

ACQUIRING_PERCENT = Decimal("1")

FBO_SINGLE_FIELDS: tuple[tuple[str, str], ...] = (
    ("fbo_deliv_to_customer_amount", "Доставка до покупателя"),
    ("fbo_return_flow_amount", "Возврат и отмена"),
)

FBS_SINGLE_FIELDS: tuple[tuple[str, str], ...] = (
    ("fbs_deliv_to_customer_amount", "Доставка до покупателя"),
    ("fbs_return_flow_amount", "Возврат и отмена"),
)

# Пары min/max для одной строки «Логистика» (FBS: обработка отправления + магистраль)
LOGISTICS_RANGES: dict[str, tuple[tuple[str, str], ...]] = {
    "fbo": (
        ("fbo_direct_flow_trans_min_amount", "fbo_direct_flow_trans_max_amount"),
    ),
    "fbs": (
        ("fbs_first_mile_min_amount", "fbs_first_mile_max_amount"),
        ("fbs_direct_flow_trans_min_amount", "fbs_direct_flow_trans_max_amount"),
    ),
}

LEGACY_LOGISTICS_MIN_LABELS = frozenset({"Магистраль, мин.", "Обработка отправления, мин."})
LEGACY_LOGISTICS_MAX_LABELS = frozenset({"Магистраль, макс.", "Обработка отправления, макс."})


def _logistics_keys_for_scheme(scheme: str) -> frozenset[str]:
    keys: list[str] = []
    for min_key, max_key in LOGISTICS_RANGES[scheme]:
        keys.extend((min_key, max_key))
    return frozenset(keys)

RETURN_LABELS = frozenset({"Возврат и отмена", "Возврат"})
RETURN_AMOUNT_KEYS = frozenset({
    "fbo_return_flow_amount",
    "fbs_return_flow_amount",
})


def _to_decimal(value) -> Decimal:
    if value is None or value == "":
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _money(value: Decimal | float | int) -> float:
    return float(_to_decimal(value).quantize(Decimal("0.01")))


def _format_amount(value: float) -> str:
    return f"{value:.2f}"


def _format_range_display(min_amount: float, max_amount: float) -> str:
    if min_amount > 0 and max_amount > 0 and abs(min_amount - max_amount) > 0.001:
        return f"{_format_amount(min_amount)} – {_format_amount(max_amount)}"
    if max_amount > 0:
        return _format_amount(max_amount)
    if min_amount > 0:
        return _format_amount(min_amount)
    return _format_amount(0)


def _block_totals(total_min: float, total_max: float) -> dict:
    return {
        "total_min": total_min,
        "total_max": total_max,
        "total": total_max,
        "total_display": _format_range_display(total_min, total_max),
    }


def _row_counts_in_total(row: dict) -> bool:
    if row.get("exclude_from_total"):
        return False
    return (row.get("label") or "").strip() not in RETURN_LABELS


def _totals_from_rows(rows: list[dict]) -> tuple[float, float]:
    total_min = Decimal(0)
    total_max = Decimal(0)
    for row in rows:
        if not isinstance(row, dict) or not _row_counts_in_total(row):
            continue
        if row.get("amount_min") is not None or row.get("amount_max") is not None:
            total_min += _to_decimal(row.get("amount_min"))
            total_max += _to_decimal(row.get("amount_max"))
        else:
            amount = _to_decimal(row.get("amount"))
            total_min += amount
            total_max += amount
    return _money(total_min), _money(total_max)


def _append_acquiring_row(rows: list[dict], total_min: Decimal, total_max: Decimal, price_dec: Decimal) -> tuple[Decimal, Decimal]:
    if price_dec <= 0:
        return total_min, total_max
    fee = (price_dec * ACQUIRING_PERCENT / Decimal(100)).quantize(Decimal("0.01"))
    total_min += fee
    total_max += fee
    rows.append(
        {
            "label": "Эквайринг",
            "amount": _money(fee),
            "percent": float(ACQUIRING_PERCENT),
            "hint": "1% от цены продажи",
        }
    )
    return total_min, total_max


def _append_logistics_row(
    rows: list[dict],
    total_min: Decimal,
    total_max: Decimal,
    comm: dict,
    scheme: str,
) -> tuple[Decimal, Decimal]:
    sum_min = Decimal(0)
    sum_max = Decimal(0)
    has_any = False

    for min_key, max_key in LOGISTICS_RANGES[scheme]:
        min_a = _to_decimal(comm.get(min_key))
        max_a = _to_decimal(comm.get(max_key))
        if min_a <= 0 and max_a <= 0:
            continue
        has_any = True
        eff_min = min_a if min_a > 0 else max_a
        eff_max = max_a if max_a > 0 else min_a
        sum_min += eff_min
        sum_max += eff_max

    if not has_any:
        return total_min, total_max

    total_min += sum_min
    total_max += sum_max
    rows.append(
        {
            "label": "Логистика",
            "amount": _money(sum_max),
            "amount_min": _money(sum_min),
            "amount_max": _money(sum_max),
            "amount_display": _format_range_display(_money(sum_min), _money(sum_max)),
            "percent": None,
            "hint": None,
        }
    )
    return total_min, total_max


def _rows_from_v5(comm: dict, price: float, *, scheme: str) -> tuple[float, float, list[dict]]:
    rows: list[dict] = []
    total_min = Decimal(0)
    total_max = Decimal(0)
    price_dec = _to_decimal(price)

    percent_key = "sales_percent_fbo" if scheme == "fbo" else "sales_percent_fbs"
    single_fields = FBO_SINGLE_FIELDS if scheme == "fbo" else FBS_SINGLE_FIELDS

    percent = _to_decimal(comm.get(percent_key))
    if percent > 0 and price_dec > 0:
        sale_fee = (price_dec * percent / Decimal(100)).quantize(Decimal("0.01"))
        total_min += sale_fee
        total_max += sale_fee
        rows.append(
            {
                "label": "Вознаграждение Ozon",
                "amount": _money(sale_fee),
                "percent": float(percent),
                "hint": f"{float(percent):g}% от цены продажи",
            }
        )

    total_min, total_max = _append_acquiring_row(rows, total_min, total_max, price_dec)
    total_min, total_max = _append_logistics_row(rows, total_min, total_max, comm, scheme)

    logistics_keys = _logistics_keys_for_scheme(scheme)
    for key, label in single_fields:
        if key in logistics_keys:
            continue
        amount = _to_decimal(comm.get(key))
        if amount <= 0:
            continue
        row = {"label": label, "amount": _money(amount), "percent": None, "hint": None}
        if label in RETURN_LABELS or key in RETURN_AMOUNT_KEYS:
            row["exclude_from_total"] = True
        else:
            total_min += amount
            total_max += amount
        rows.append(row)

    return _money(total_min), _money(total_max), rows


def _rows_from_info_commissions(
    info_item: dict | None,
    scheme: str,
    sale_price: float,
) -> tuple[float, float, list[dict]] | None:
    if not isinstance(info_item, dict):
        return None
    entries = info_item.get("commissions")
    if not isinstance(entries, list):
        return None

    target = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        schema = (entry.get("sale_schema") or "").strip().lower()
        if scheme == "fbo" and schema == "fbo":
            target = entry
            break
        if scheme == "fbs" and schema in ("fbs", "rfbs"):
            target = entry
            break

    if not target:
        return None

    rows: list[dict] = []
    total_min = Decimal(0)
    total_max = Decimal(0)
    price_dec = _to_decimal(sale_price)

    ozon_fee = _to_decimal(target.get("value"))
    percent = target.get("percent")
    percent_dec = _to_decimal(percent)
    if percent_dec > 0 and price_dec > 0:
        ozon_fee = (price_dec * percent_dec / Decimal(100)).quantize(Decimal("0.01"))
        total_min += ozon_fee
        total_max += ozon_fee
        rows.append(
            {
                "label": "Вознаграждение Ozon",
                "amount": _money(ozon_fee),
                "percent": float(percent_dec),
                "hint": f"{float(percent_dec):g}% от цены продажи",
            }
        )
    elif ozon_fee > 0:
        total_min += ozon_fee
        total_max += ozon_fee
        rows.append({"label": "Комиссия Ozon", "amount": _money(ozon_fee), "percent": None, "hint": None})

    total_min, total_max = _append_acquiring_row(rows, total_min, total_max, price_dec)

    delivery = _to_decimal(target.get("delivery_amount"))
    if delivery > 0:
        total_min += delivery
        total_max += delivery
        rows.append({"label": "Доставка", "amount": _money(delivery), "percent": None, "hint": None})
    ret = _to_decimal(target.get("return_amount"))
    if ret > 0:
        rows.append(
            {
                "label": "Возврат",
                "amount": _money(ret),
                "percent": None,
                "hint": None,
                "exclude_from_total": True,
            }
        )

    if not rows:
        return None

    return _money(total_min), _money(total_max), rows


def _ensure_acquiring_row(rows: list[dict], sale_price: float) -> list[dict]:
    for row in rows:
        if isinstance(row, dict) and (row.get("label") or "").strip() == "Эквайринг":
            return rows
    price_dec = _to_decimal(sale_price)
    if price_dec <= 0:
        return rows
    fee = (price_dec * ACQUIRING_PERCENT / Decimal(100)).quantize(Decimal("0.01"))
    new_rows = list(rows)
    insert_at = 0
    for idx, row in enumerate(new_rows):
        if isinstance(row, dict) and (row.get("label") or "").strip() == "Вознаграждение Ozon":
            insert_at = idx + 1
            break
    new_rows.insert(
        insert_at,
        {
            "label": "Эквайринг",
            "amount": _money(fee),
            "percent": float(ACQUIRING_PERCENT),
            "hint": "1% от цены продажи",
        },
    )
    return new_rows


def _fix_logistics_row_bounds(row: dict) -> dict:
    if row.get("amount_min") is not None and row.get("amount_max") is not None:
        return row
    display = str(row.get("amount_display") or "")
    for sep in ("–", "-"):
        if sep in display:
            parts = [p.strip() for p in display.split(sep, 1)]
            if len(parts) == 2:
                try:
                    eff_min = float(parts[0].replace(",", "."))
                    eff_max = float(parts[1].replace(",", "."))
                    return {
                        **row,
                        "amount_min": eff_min,
                        "amount_max": eff_max,
                        "amount": eff_max,
                    }
                except ValueError:
                    break
    amount = float(row.get("amount") or 0)
    return {**row, "amount_min": amount, "amount_max": amount}


def _normalize_commission_rows(rows: list[dict]) -> list[dict]:
    """Сводит все логистические составляющие в одну строку «Логистика»."""
    normalized: list[dict] = []
    logistics_min = Decimal(0)
    logistics_max = Decimal(0)
    has_logistics = False

    for row in rows:
        if not isinstance(row, dict):
            continue
        label = (row.get("label") or "").strip()

        if label in LEGACY_LOGISTICS_MIN_LABELS:
            logistics_min += _to_decimal(row.get("amount"))
            has_logistics = True
            continue
        if label in LEGACY_LOGISTICS_MAX_LABELS:
            logistics_max += _to_decimal(row.get("amount"))
            has_logistics = True
            continue
        if label == "Логистика":
            fixed = _fix_logistics_row_bounds(row)
            logistics_min += _to_decimal(fixed.get("amount_min"))
            logistics_max += _to_decimal(fixed.get("amount_max"))
            has_logistics = True
            continue

        normalized.append(row)

    if has_logistics:
        eff_min = _money(logistics_min if logistics_min > 0 else logistics_max)
        eff_max = _money(logistics_max if logistics_max > 0 else logistics_min)
        normalized.append(
            {
                "label": "Логистика",
                "amount": eff_max,
                "amount_min": eff_min,
                "amount_max": eff_max,
                "amount_display": _format_range_display(eff_min, eff_max),
                "percent": None,
                "hint": None,
            }
        )
    return normalized


def _rescale_percent_rows(rows: list[dict], sale_price: float) -> list[dict]:
    """Пересчитывает строки с процентом от актуальной цены продажи."""
    price_dec = _to_decimal(sale_price)
    if price_dec <= 0:
        return rows

    updated: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            updated.append(row)
            continue

        percent = row.get("percent")
        if percent is None or _to_decimal(percent) <= 0:
            updated.append(row)
            continue

        percent_dec = _to_decimal(percent)
        fee = (price_dec * percent_dec / Decimal(100)).quantize(Decimal("0.01"))
        label = (row.get("label") or "").strip()
        new_row = {
            **row,
            "amount": _money(fee),
            "percent": float(percent_dec),
        }
        new_row.pop("amount_min", None)
        new_row.pop("amount_max", None)
        new_row.pop("amount_display", None)

        if label == "Эквайринг":
            new_row["hint"] = "1% от цены продажи"
        elif "Ozon" in label:
            new_row["hint"] = f"{float(percent_dec):g}% от цены продажи"

        updated.append(new_row)
    return updated


def _enrich_commission_block(block: dict, sale_price: float) -> dict:
    rows = _normalize_commission_rows(block.get("rows") or [])
    rows = _rescale_percent_rows(rows, sale_price)
    rows = _ensure_acquiring_row(rows, sale_price)
    total_min, total_max = _totals_from_rows(rows)
    totals = _block_totals(total_min, total_max)
    return {**block, "rows": rows, "has_data": bool(rows), **totals}


def extract_product_commissions(
    price_item: dict | None,
    info_item: dict | None,
    sale_price: float,
) -> dict:
    """Сводка комиссий для сохранения в Product."""
    details: dict[str, dict] = {}
    for scheme in ("fbo", "fbs"):
        rows: list[dict] = []
        total_min = 0.0
        total_max = 0.0
        comm = price_item.get("commissions") if isinstance(price_item, dict) else None
        if isinstance(comm, dict) and comm:
            total_min, total_max, rows = _rows_from_v5(comm, sale_price, scheme=scheme)
        else:
            fallback = _rows_from_info_commissions(info_item, scheme, sale_price)
            if fallback:
                total_min, total_max, rows = fallback

        totals = _block_totals(total_min, total_max)
        details[scheme] = {"rows": rows, "has_data": bool(rows), **totals}

    return {
        "fbo_total": details["fbo"]["total"] if details["fbo"]["has_data"] else None,
        "fbs_total": details["fbs"]["total"] if details["fbs"]["has_data"] else None,
        "details": details,
    }


def commission_detail_for_api(
    details: dict | None,
    scheme: str,
    *,
    sale_price: float = 0,
) -> dict | None:
    if not isinstance(details, dict):
        return None
    block = details.get(scheme)
    if not isinstance(block, dict) or not block.get("has_data"):
        return None
    return _enrich_commission_block(block, sale_price)
