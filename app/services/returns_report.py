"""Отчёт по возвратам FBO/FBS."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from flask import current_app

from app.datetime_fmt import format_return_status_date
from app.models import Product
from app.ozon.returns import fetch_returns_list, fetch_rfbs_return

MAX_RETURNS_PERIOD_DAYS = 365
RETURNS_CACHE_DIR = "returns_cache"

RETURN_TYPE_LABELS = {
    "Cancellation": "Отмена",
    "FullReturn": "Возврат",
    "PartialReturn": "Возврат",
    "ClientReturn": "Возврат",
    "Unknown": "Возврат",
}

RFBS_STATE_LABELS = {
    "ReceivedBySeller": "Получен",
    "Delivering": "Едет на склад Ozon",
    "Checkout": "На проверке",
    "Arbitration": "Спор",
    "Approved": "Одобрена",
    "Rejected": "Отклонена вами",
    "New": "Новая",
}

STATUS_TONE_TRANSIT = {
    "MovingToOzon",
    "MovingToSeller",
    "ReturningToSellerByCourier",
    "WaitingShipment",
    "Delivering",
}
STATUS_TONE_WAREHOUSE = {
    "ReturnedToOzon",
    "ReturnCompensated",
    "MoneyReturned",
    "MoneyReturnedBySystem",
    "Approved",
    "ApprovedByOzon",
    "ArrivedAtReturnPlace",
}
STATUS_TONE_REJECTED = {
    "Rejected",
    "CrmRejected",
    "CancelledDisputeNotOpen",
    "CompensationRejected",
    "CompensationRejectedBySeller",
    "CompensationRejectedBySla",
    "Utilized",
    "Cancelled",
}


def _parse_ozon_datetime(value) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    normalized = text.replace(" ", "T", 1) if " " in text and "T" not in text else text
    if "." in normalized:
        head, tail = normalized.split(".", 1)
        suffix = ""
        for index, char in enumerate(tail):
            if char.isdigit():
                continue
            suffix = tail[index:]
            tail = tail[:index]
            break
        if tail:
            normalized = f"{head}.{tail[:6]}{suffix}"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _build_v1_status_dates_index(rows: list[dict]) -> dict[str, datetime]:
    index: dict[str, datetime] = {}
    for row in rows:
        if row.get("_return_source") == "rfbs":
            continue
        status_dt = _v1_status_change_moment(row)
        if not status_dt:
            continue
        for key in (
            str(row.get("id") or "").strip(),
            str(row.get("posting_number") or "").strip(),
            str(row.get("order_number") or "").strip(),
        ):
            if key:
                index.setdefault(key, status_dt)
    return index


def _collect_datetime_candidates(payload: dict | None) -> list[tuple[str, datetime]]:
    if not isinstance(payload, dict):
        return []

    priority_keys = (
        "change_moment",
        "state_change_moment",
        "status_change_moment",
        "modified_at",
        "updated_at",
        "approved_at",
        "received_at",
        "final_moment",
        "return_date",
        "created_at",
    )
    found: list[tuple[str, datetime]] = []
    seen: set[str] = set()

    def walk(node, path: str = "") -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            current_path = f"{path}.{key}" if path else str(key)
            if isinstance(value, dict):
                walk(value, current_path)
                continue
            if current_path in seen:
                continue
            key_name = str(key)
            if key_name.endswith(("_moment", "_at", "_date")) or key_name in priority_keys:
                dt = _parse_ozon_datetime(value)
                if dt:
                    seen.add(current_path)
                    found.append((key_name, dt))

    walk(payload)

    def sort_key(item: tuple[str, datetime]) -> int:
        key_name = item[0]
        if key_name in priority_keys:
            return priority_keys.index(key_name)
        return len(priority_keys)

    found.sort(key=sort_key)
    return found


def _resolve_rfbs_status_date(
    row: dict,
    detail: dict | None,
    v1_status_dates: dict[str, datetime],
) -> datetime | None:
    for source in (detail, row):
        if not isinstance(source, dict):
            continue
        for _, dt in _collect_datetime_candidates(source):
            return dt

    for source in (row, detail):
        if not isinstance(source, dict):
            continue
        for key in (
            str(source.get("posting_number") or "").strip(),
            str(source.get("return_number") or "").strip(),
            str(source.get("return_id") or "").strip(),
            str(source.get("order_number") or "").strip(),
        ):
            if key and key in v1_status_dates:
                return v1_status_dates[key]
    return None


def _catalog_lookup(user_id: int) -> dict[str, Product]:
    catalog: dict[str, Product] = {}
    for product in Product.query.filter_by(user_id=user_id).all():
        if product.ozon_product_id:
            catalog[str(product.ozon_product_id)] = product
        if product.sku:
            catalog.setdefault(str(product.sku), product)
        if product.offer_id:
            catalog.setdefault(str(product.offer_id), product)
    return catalog


def _find_catalog_product(catalog: dict[str, Product], product: dict) -> Product | None:
    sku = str(product.get("sku") or "").strip()
    offer_id = str(product.get("offer_id") or "").strip()
    if sku and sku in catalog:
        return catalog[sku]
    if offer_id and offer_id in catalog:
        return catalog[offer_id]
    return None


def format_return_scheme(schema: str | None) -> str:
    text = str(schema or "").strip().upper()
    if not text:
        return "—"
    if text == "RFBS" or "RFBS" in text:
        return "realFBS"
    if text == "FBO" or text.endswith("FBO"):
        return "FBO"
    if text == "FBS" or text.endswith("FBS"):
        return "FBS"
    return text


def format_return_type(type_value: str | None) -> str:
    key = str(type_value or "").strip()
    if not key:
        return "Возврат"
    return RETURN_TYPE_LABELS.get(key, "Возврат")


def _status_date_display(status_dt: datetime | None) -> str:
    return format_return_status_date(status_dt)


def _v1_status_change_moment(row: dict) -> datetime | None:
    visual = row.get("visual") if isinstance(row.get("visual"), dict) else {}
    return _parse_ozon_datetime(visual.get("change_moment"))


def _extract_status_change_moment(payload: dict) -> datetime | None:
    visual = payload.get("visual") if isinstance(payload.get("visual"), dict) else {}
    dt = _parse_ozon_datetime(visual.get("change_moment"))
    if dt:
        return dt

    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    for key in ("change_moment", "state_change_moment", "changed_at", "updated_at"):
        dt = _parse_ozon_datetime(state.get(key))
        if dt:
            return dt

    for key in ("change_moment", "state_change_moment", "updated_at"):
        dt = _parse_ozon_datetime(payload.get(key))
        if dt:
            return dt
    return None


def _extract_return_reason(payload: dict) -> str | None:
    reason = payload.get("return_reason_name")
    if reason:
        return str(reason)

    raw_reason = payload.get("return_reason")
    if isinstance(raw_reason, dict):
        for key in ("name", "display_name", "title"):
            value = raw_reason.get(key)
            if value:
                return str(value)
    elif raw_reason:
        return str(raw_reason)
    return None


def _rfbs_status_label(state: dict, fallback: str = "—") -> str:
    state_name = str(state.get("state_name") or "").strip()
    if state_name:
        return state_name

    sys_name = str(state.get("state") or "").strip()
    if sys_name in RFBS_STATE_LABELS:
        return RFBS_STATE_LABELS[sys_name]

    for key in ("display_name", "group_state", "money_return_state_name"):
        value = str(state.get(key) or "").strip()
        if value and value.lower() != "all":
            if value in RFBS_STATE_LABELS:
                return RFBS_STATE_LABELS[value]
            return value
    return fallback


def return_status_tone(sys_name: str | None, display_name: str | None) -> str:
    sys_key = str(sys_name or "").strip()
    if sys_key in STATUS_TONE_TRANSIT:
        return "transit"
    if sys_key in STATUS_TONE_WAREHOUSE:
        return "warehouse"
    if sys_key in STATUS_TONE_REJECTED:
        return "rejected"
    if sys_key == "ReceivedBySeller":
        return "received"

    text = str(display_name or "").strip().lower()
    if "едет" in text and "ozon" in text:
        return "transit"
    if "на складе ozon" in text:
        return "warehouse"
    if "отклон" in text or text == "отклонена вами":
        return "rejected"
    if text == "получен" or text.startswith("получен"):
        return "received"
    if text in {"approved", "rejected", "delivering", "checkout", "arbitration"}:
        mapping = {
            "approved": "warehouse",
            "rejected": "rejected",
            "delivering": "transit",
            "checkout": "transit",
            "arbitration": "rejected",
        }
        return mapping.get(text, "default")
    return "default"


def _product_fields(catalog: dict[str, Product], product: dict) -> dict:
    catalog_product = _find_catalog_product(catalog, product)
    name = catalog_product.name if catalog_product else str(product.get("name") or "—")
    offer_id = (
        catalog_product.offer_id
        if catalog_product and catalog_product.offer_id
        else str(product.get("offer_id") or "—")
    )
    barcode = "—"
    if catalog_product:
        barcode = catalog_product.barcode_display()
    elif product.get("barcode"):
        barcode = str(product.get("barcode"))
    return {
        "name": name,
        "offer_id": offer_id or "—",
        "barcode": barcode,
        "thumbnail_url": catalog_product.thumbnail_url if catalog_product else None,
    }


def _normalize_v1_return_row(row: dict, catalog: dict[str, Product]) -> dict:
    product = row.get("product") if isinstance(row.get("product"), dict) else {}
    visual = row.get("visual") if isinstance(row.get("visual"), dict) else {}
    status = visual.get("status") if isinstance(visual.get("status"), dict) else {}
    product_fields = _product_fields(catalog, product)

    status_dt = _v1_status_change_moment(row)
    display_name = str(status.get("display_name") or "—")
    sys_name = str(status.get("sys_name") or "")

    return {
        "return_id": str(row.get("id") or ""),
        "scheme": format_return_scheme(row.get("schema")),
        "status_date": status_dt,
        "status_date_display": _status_date_display(status_dt),
        "application_number": str(row.get("id") or "—"),
        "application_type": format_return_type(row.get("type")),
        "status": display_name,
        "status_tone": return_status_tone(sys_name, display_name),
        "reason": str(row.get("return_reason_name") or "—"),
        "posting_number": str(row.get("posting_number") or "").strip(),
        **product_fields,
    }


def _normalize_rfbs_return_row(
    row: dict,
    catalog: dict[str, Product],
    detail: dict | None = None,
    v1_status_dates: dict[str, datetime] | None = None,
) -> dict:
    payload = detail if isinstance(detail, dict) else row
    product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
    if not product and isinstance(row.get("product"), dict):
        product = row["product"]
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    if not state and isinstance(row.get("state"), dict):
        state = row["state"]
    product_fields = _product_fields(catalog, product)

    status_dt = _resolve_rfbs_status_date(row, detail, v1_status_dates or {})
    display_name = _rfbs_status_label(state, "—")
    sys_name = str(state.get("state") or "")

    reason = _extract_return_reason(payload) or _extract_return_reason(row) or "—"
    app_type = format_return_type(payload.get("type") or row.get("type"))
    if app_type == "Возврат" and "отмен" in reason.lower():
        app_type = "Отмена"

    posting_number = str(
        payload.get("posting_number")
        or row.get("posting_number")
        or ""
    ).strip()

    return {
        "return_id": f"rfbs:{row.get('return_id') or row.get('id') or ''}",
        "scheme": "realFBS",
        "status_date": status_dt,
        "status_date_display": _status_date_display(status_dt),
        "application_number": str(
            payload.get("return_number") or row.get("return_number") or row.get("return_id") or "—"
        ),
        "application_type": app_type,
        "status": display_name,
        "status_tone": return_status_tone(sys_name, display_name),
        "reason": reason,
        "posting_number": posting_number,
        **product_fields,
    }


def _normalize_return_row(
    row: dict,
    catalog: dict[str, Product],
    rfbs_details: dict[int, dict] | None = None,
    v1_status_dates: dict[str, datetime] | None = None,
) -> dict:
    if row.get("_return_source") == "rfbs":
        return_id = row.get("return_id") or row.get("id")
        detail = None
        if rfbs_details and return_id is not None:
            try:
                detail = rfbs_details.get(int(return_id))
            except (TypeError, ValueError):
                detail = None
        return _normalize_rfbs_return_row(row, catalog, detail, v1_status_dates)
    return _normalize_v1_return_row(row, catalog)


def _load_rfbs_details(client_id: str, api_key: str, rows: list[dict]) -> dict[int, dict]:
    details: dict[int, dict] = {}
    for row in rows:
        if row.get("_return_source") != "rfbs":
            continue
        return_id = row.get("return_id") or row.get("id")
        try:
            return_id_int = int(return_id)
        except (TypeError, ValueError):
            continue
        if return_id_int in details:
            continue
        detail = fetch_rfbs_return(client_id, api_key, return_id_int)
        if detail:
            details[return_id_int] = detail
    return details


def build_returns_report(user, date_from: date, date_to: date) -> dict:
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле.", "returns": []}

    if date_from > date_to:
        return {"ok": False, "error": "Дата начала позже даты окончания.", "returns": []}

    period_days = (date_to - date_from).days + 1
    if period_days > MAX_RETURNS_PERIOD_DAYS:
        return {
            "ok": False,
            "error": f"Максимальный период — {MAX_RETURNS_PERIOD_DAYS} дней.",
            "returns": [],
        }

    try:
        rows = fetch_returns_list(user.ozon_client_id, user.ozon_api_key, date_from, date_to)
        catalog = _catalog_lookup(user.id)
        v1_status_dates = _build_v1_status_dates_index(rows)
        rfbs_details = _load_rfbs_details(user.ozon_client_id, user.ozon_api_key, rows)
        items = [
            _normalize_return_row(row, catalog, rfbs_details, v1_status_dates)
            for row in rows
        ]
        items.sort(
            key=lambda item: (
                item["status_date"] or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        return {
            "ok": True,
            "returns": items,
            "summary": {"return_count": len(items)},
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "returns": []}


def _cache_path(user_id: int) -> Path:
    base = Path(current_app.instance_path) / RETURNS_CACHE_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / f"user_{user_id}.json"


def _cache_ready_items(items: list[dict]) -> list[dict]:
    cached: list[dict] = []
    for item in items:
        row = dict(item)
        status_dt = row.pop("status_date", None)
        if isinstance(status_dt, datetime):
            row["status_date_iso"] = status_dt.isoformat()
        cached.append(row)
    return cached


def save_returns_report_cache(
    user_id: int,
    date_from: date,
    date_to: date,
    items: list[dict],
    summary: dict | None = None,
) -> None:
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "returns": _cache_ready_items(items),
        "summary": summary or {"return_count": len(items)},
    }
    _cache_path(user_id).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def get_returns_report_cache(user_id: int) -> dict | None:
    path = _cache_path(user_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        returns = data.get("returns")
        if not isinstance(returns, list):
            return None
        return data
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _diff_returns_cache(
    old_cache: dict | None,
    items: list[dict],
) -> tuple[list[dict], list[tuple[dict, str]]]:
    """Сравнение кэша с новыми данными: новые возвраты и смены статуса."""
    if old_cache is None:
        return [], []

    old_returns = old_cache.get("returns")
    if not isinstance(old_returns, list):
        return [], []

    old_by_id = {
        str(row.get("return_id") or ""): row
        for row in old_returns
        if str(row.get("return_id") or "")
    }

    new_items = [
        item
        for item in items
        if str(item.get("return_id") or "") not in old_by_id
    ]
    status_changes: list[tuple[dict, str]] = []
    for item in items:
        return_id = str(item.get("return_id") or "")
        if not return_id or return_id not in old_by_id:
            continue
        old_status = str(old_by_id[return_id].get("status") or "")
        new_status = str(item.get("status") or "")
        if old_status and new_status and old_status != new_status:
            status_changes.append((item, old_status))

    return new_items, status_changes


def run_returns_check(user, *, notify: bool = True) -> dict:
    """Регламентная проверка возвратов за последние 30 дней."""
    from app.services.returns_period import default_returns_period

    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле.", "skipped": True}

    date_from, date_to = default_returns_period()
    old_cache = get_returns_report_cache(user.id)
    report = build_returns_report(user, date_from, date_to)
    if not report.get("ok"):
        return report

    items = report.get("returns") or []
    summary = report.get("summary") or {"return_count": len(items)}

    if notify:
        new_items, status_changes = _diff_returns_cache(old_cache, items)
        if new_items or status_changes:
            from app.services.notifications_service import (
                notify_new_returns,
                notify_return_status_changed,
            )

            if new_items:
                notify_new_returns(user, new_items)
            for item, old_status in status_changes:
                notify_return_status_changed(user, item, old_status)

    save_returns_report_cache(user.id, date_from, date_to, items, summary)

    return {
        "ok": True,
        "return_count": summary.get("return_count", len(items)),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "message": (
            f"Возвраты за {date_from.strftime('%d.%m.%Y')}–{date_to.strftime('%d.%m.%Y')}: "
            f"{summary.get('return_count', len(items))}."
        ),
    }
