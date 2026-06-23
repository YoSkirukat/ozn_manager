"""Загрузка отправлений FBO/FBS из Ozon Seller API."""

from datetime import date, datetime, time, timezone
from decimal import Decimal

from app.ozon.client import _post

POSTING_LIST_LIMIT = 1000
LIST_WITH = {"analytics_data": True, "financial_data": True}


def _iso_range(date_from: date, date_to: date) -> tuple[str, str]:
    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    end = datetime.combine(date_to, time.max.replace(microsecond=0), tzinfo=timezone.utc)
    return start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), end.strftime("%Y-%m-%dT%H:%M:%S.999Z")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _extract_total(posting: dict) -> Decimal:
    financial = posting.get("financial_data")
    if isinstance(financial, dict):
        products = financial.get("products") or []
    elif isinstance(financial, list):
        products = financial
    else:
        products = posting.get("products") or []
    if not isinstance(products, list):
        products = []
    total = Decimal(0)
    for item in products:
        if not isinstance(item, dict):
            continue
        price = Decimal(str(item.get("price") or item.get("customer_price") or 0))
        qty = int(item.get("quantity") or 1)
        total += price * qty
    if total > 0:
        return total.quantize(Decimal("0.01"))

    for key in ("total_price", "price", "amount"):
        raw = posting.get(key)
        if raw is not None:
            try:
                return Decimal(str(raw)).quantize(Decimal("0.01"))
            except Exception:
                pass
    return Decimal(0)


def normalize_posting(posting: dict, scheme: str) -> dict | None:
    if not isinstance(posting, dict):
        return None
    posting_number = str(posting.get("posting_number") or "").strip()
    if not posting_number:
        return None

    order_date = _parse_datetime(
        posting.get("in_process_at") or posting.get("created_at") or posting.get("shipment_date")
    )
    if order_date is None:
        order_date = datetime.now(timezone.utc)

    return {
        "ozon_order_id": posting_number,
        "status": str(posting.get("status") or "unknown"),
        "scheme": scheme,
        "total": _extract_total(posting),
        "order_date": order_date,
        "raw_data": posting,
    }


def _parse_list_response(data: dict) -> tuple[list[dict], bool]:
    """Ozon может вернуть result как объект или список отправлений."""
    result = data.get("result")
    if isinstance(result, list):
        batch = [p for p in result if isinstance(p, dict)]
        return batch, False
    if isinstance(result, dict):
        postings = result.get("postings") or []
        if isinstance(postings, list):
            batch = [p for p in postings if isinstance(p, dict)]
        else:
            batch = []
        return batch, bool(result.get("has_next"))
    return [], False


def _fetch_posting_pages(
    client_id: str,
    api_key: str,
    path: str,
    since: str,
    to: str,
) -> list[dict]:
    items: list[dict] = []
    offset = 0
    while True:
        payload = {
            "dir": "ASC",
            "filter": {"since": since, "to": to},
            "limit": POSTING_LIST_LIMIT,
            "offset": offset,
            "with": LIST_WITH,
        }
        data = _post(client_id, api_key, path, payload)
        if not isinstance(data, dict):
            break
        batch, has_next = _parse_list_response(data)
        items.extend(batch)
        if not has_next or not batch:
            break
        offset += len(batch)
    return items


def fetch_fbs_postings(client_id: str, api_key: str, date_from: date, date_to: date) -> list[dict]:
    since, to = _iso_range(date_from, date_to)
    postings = _fetch_posting_pages(client_id, api_key, "/v3/posting/fbs/list", since, to)
    return [p for p in (normalize_posting(item, "FBS") for item in postings) if p]


def fetch_fbo_postings(client_id: str, api_key: str, date_from: date, date_to: date) -> list[dict]:
    since, to = _iso_range(date_from, date_to)
    postings = _fetch_posting_pages(client_id, api_key, "/v2/posting/fbo/list", since, to)
    return [p for p in (normalize_posting(item, "FBO") for item in postings) if p]
