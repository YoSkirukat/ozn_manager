"""Загрузка отправлений FBO/FBS из Ozon Seller API."""

from datetime import date, datetime, time, timezone
from decimal import Decimal

from app.ozon.client import _post, _post_content
from app.ozon.money import money_amount

# Ozon отключил прежние методы списка: /v3/posting/fbs/list отвечает 429
# («request rate limit per second»), а /v2/posting/fbo/list — 400
# «obsolete method cannot be used». Рабочие методы возвращают не более 100
# отправлений на страницу и пагинируются курсором.
POSTING_LIST_LIMIT = 100
MAX_LIST_PAGES = 100
FBS_LIST_PATH = "/v4/posting/fbs/list"
FBO_LIST_PATH = "/v3/posting/fbo/list"
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
        # `price` в списке отправлений — объект {"amount", "currency"}, в финансовых данных — число.
        price = money_amount(item.get("price")) or money_amount(item.get("customer_price"))
        qty = int(item.get("quantity") or 1)
        total += price * qty
    if total > 0:
        return total.quantize(Decimal("0.01"))

    for key in ("total_price", "price", "amount"):
        raw = posting.get(key)
        if raw is not None:
            return money_amount(raw).quantize(Decimal("0.01"))
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


def _parse_list_response(data: dict) -> tuple[list[dict], bool, str]:
    """Разбирает ответ методов списка отправлений.

    Актуальные методы (`/v4/posting/fbs/list`, `/v3/posting/fbo/list`) отдают
    `postings`, `has_next` и `cursor` в корне ответа. Старый формат с вложенным
    `result` поддерживаем для совместимости.
    """
    if not isinstance(data, dict):
        return [], False, ""

    result = data.get("result")
    if isinstance(result, list):
        return [p for p in result if isinstance(p, dict)], False, ""

    source = result if isinstance(result, dict) else data

    postings = source.get("postings") or []
    batch = [p for p in postings if isinstance(p, dict)] if isinstance(postings, list) else []
    cursor = str(source.get("cursor") or "").strip()
    return batch, bool(source.get("has_next")), cursor


def _fetch_posting_pages(
    client_id: str,
    api_key: str,
    path: str,
    since: str,
    to: str,
) -> list[dict]:
    """Постранично загружает отправления за период (курсорная пагинация Ozon)."""
    items: list[dict] = []
    cursor = ""
    for _ in range(MAX_LIST_PAGES):
        payload = {
            "dir": "ASC",
            "filter": {"since": since, "to": to},
            "limit": POSTING_LIST_LIMIT,
            "cursor": cursor,
            "with": LIST_WITH,
        }
        data = _post(client_id, api_key, path, payload)
        batch, has_next, next_cursor = _parse_list_response(data)
        items.extend(batch)
        if not has_next or not batch or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return items


def fetch_fbs_postings(client_id: str, api_key: str, date_from: date, date_to: date) -> list[dict]:
    since, to = _iso_range(date_from, date_to)
    postings = _fetch_posting_pages(client_id, api_key, FBS_LIST_PATH, since, to)
    return [p for p in (normalize_posting(item, "FBS") for item in postings) if p]


def fetch_fbo_postings(client_id: str, api_key: str, date_from: date, date_to: date) -> list[dict]:
    since, to = _iso_range(date_from, date_to)
    postings = _fetch_posting_pages(client_id, api_key, FBO_LIST_PATH, since, to)
    return [p for p in (normalize_posting(item, "FBO") for item in postings) if p]


def ship_fbs_posting(
    client_id: str,
    api_key: str,
    posting_number: str,
    products: list[dict],
) -> dict:
    """Сборка отправления FBS: переводит его в статус «Ожидает отгрузки».

    products: [{"product_id": int, "quantity": int}]
    """
    payload = {
        "posting_number": posting_number,
        "packages": [{"products": products}],
        "with": {"additional_data": True},
    }
    return _post(client_id, api_key, "/v4/posting/fbs/ship", payload)


def fetch_fbs_package_label(client_id: str, api_key: str, posting_number: str) -> bytes:
    """PDF-этикетка отправления FBS (стикер для наклейки на посылку)."""
    return _post_content(
        client_id,
        api_key,
        "/v2/posting/fbs/package-label",
        {"posting_number": [posting_number]},
    )


def posting_status_from_response(data: dict | None, posting_number: str) -> str | None:
    """Статус отправления из ответа методов вроде /v4/posting/fbs/ship."""
    if not isinstance(data, dict):
        return None

    result = data.get("result")
    rows: list[dict] = []
    if isinstance(result, list):
        rows = [row for row in result if isinstance(row, dict)]
    elif isinstance(result, dict):
        rows = [result]

    additional = data.get("additional_data")
    if isinstance(additional, list):
        rows.extend(row for row in additional if isinstance(row, dict))

    for row in rows:
        if posting_number and str(row.get("posting_number") or "") != posting_number:
            continue
        status = str(row.get("status") or "").strip()
        if status:
            return status
    for row in rows:
        status = str(row.get("status") or "").strip()
        if status:
            return status
    return None

