"""Загрузка отправлений FBO/FBS из Ozon Seller API."""

import time
from datetime import date, datetime, time as datetime_time, timezone
from decimal import Decimal

import requests

from app.ozon.client import _post
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

# Этикетки FBS. С 02.11.2026 метод /v2/posting/fbs/package-label отключён
# («obsolete method cannot be used»): Ozon перевёл печать на асинхронную схему —
# сначала создаём задание на формирование, затем забираем готовый файл по task_id.
FBS_LABEL_CREATE_PATH = "/v3/posting/fbs/package-label/create"
FBS_LABEL_GET_PATH = "/v2/posting/fbs/package-label/get"
# Ozon формирует файл не мгновенно: опрашиваем задание с паузой, но укладываемся
# в дефолтный таймаут gunicorn (30 с), иначе воркер убьют до ответа пользователю.
LABEL_POLL_INTERVAL_SEC = 2.0
LABEL_WAIT_SEC = 25.0
LABEL_FILE_TIMEOUT_SEC = 20
LABEL_PENDING_MESSAGE = (
    "Ozon ещё формирует этикетку. Подождите минуту и попробуйте скачать её снова."
)


def _iso_range(date_from: date, date_to: date) -> tuple[str, str]:
    start = datetime.combine(date_from, datetime_time.min, tzinfo=timezone.utc)
    end = datetime.combine(
        date_to, datetime_time.max.replace(microsecond=0), tzinfo=timezone.utc
    )
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


def _label_task_id(client_id: str, api_key: str, posting_number: str) -> int:
    """Создаёт задание Ozon на формирование этикетки и возвращает его id."""
    data = _post(
        client_id,
        api_key,
        FBS_LABEL_CREATE_PATH,
        {"posting_numbers": [posting_number]},
    )
    tasks = [task for task in (data.get("tasks") or []) if isinstance(task, dict)]
    # Ozon готовит обычную и маленькую этикетки; кнопка на странице — про обычную.
    tasks.sort(key=lambda task: str(task.get("task_type") or "") != "big_label")
    for task in tasks:
        try:
            task_id = int(task.get("task_id"))
        except (TypeError, ValueError):
            continue
        if task_id > 0:
            return task_id
    raise RuntimeError("Ozon не создал задание на формирование этикетки.")


def _label_error_message(data: dict, status: dict) -> str:
    """Текст ошибки формирования этикетки из ответа /v2/posting/fbs/package-label/get."""
    error = data.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        if message:
            return f"Ozon: {message}"
    unprinted = status.get("unprinted_postings")
    if isinstance(unprinted, list):
        for row in unprinted:
            if isinstance(row, dict):
                message = str(row.get("message") or "").strip()
                if message:
                    return f"Ozon: {message}"
    return "Ozon не смог сформировать этикетку отправления."


def _wait_label_file(client_id: str, api_key: str, task_id: int) -> str:
    """Опрашивает задание Ozon, пока файл с этикеткой не будет готов."""
    deadline = time.monotonic() + LABEL_WAIT_SEC
    while True:
        data = _post(client_id, api_key, FBS_LABEL_GET_PATH, {"task_id": task_id})
        if not isinstance(data, dict):
            data = {}
        status = data.get("status") if isinstance(data.get("status"), dict) else {}
        code = str(status.get("code") or "").strip().lower()
        file_url = str(data.get("file_url") or "").strip()
        # `completed` — файл готов; пустой код со ссылкой тоже отдаём, чтобы не
        # зациклиться, если Ozon опустит статус.
        if file_url and code in ("completed", ""):
            return file_url
        # Задание завершилось без файла: причину Ozon присылает в unprinted_postings.
        if code in ("error", "completed"):
            raise RuntimeError(_label_error_message(data, status))
        if time.monotonic() >= deadline:
            raise RuntimeError(LABEL_PENDING_MESSAGE)
        time.sleep(LABEL_POLL_INTERVAL_SEC)


def _download_label_file(file_url: str) -> bytes:
    """Скачивает готовый файл этикетки по ссылке из ответа Ozon."""
    try:
        resp = requests.get(file_url, timeout=LABEL_FILE_TIMEOUT_SEC)
    except requests.RequestException as exc:
        raise RuntimeError(f"Ozon: не удалось скачать файл этикетки ({exc}).") from exc
    if resp.status_code != 200:
        raise RuntimeError(
            f"Ozon: не удалось скачать файл этикетки (HTTP {resp.status_code})."
        )
    if not resp.content:
        raise RuntimeError("Ozon вернул пустой файл этикетки.")
    return resp.content


def fetch_fbs_package_label(client_id: str, api_key: str, posting_number: str) -> bytes:
    """PDF-этикетка отправления FBS (стикер для наклейки на посылку).

    Ozon формирует этикетки асинхронно: создаём задание, дожидаемся готового
    файла по `task_id` и скачиваем его по выданной ссылке.
    """
    task_id = _label_task_id(client_id, api_key, posting_number)
    file_url = _wait_label_file(client_id, api_key, task_id)
    return _download_label_file(file_url)


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

