"""Клиент Ozon Seller API."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import random
import tempfile
import threading
import time

import requests

try:  # POSIX: общий троттлинг между веб-процессом и планировщиком.
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

OZON_API_BASE = "https://api-seller.ozon.ru"
PRODUCT_LIST_LIMIT = 1000
INFO_BATCH_SIZE = 100

# Лимит Ozon «per second»: сериализуем запросы по client_id и повторяем при 429.
API_MAX_RETRIES = 8
# Ozon режет лимит на аккаунт целиком, а не на метод: даже честная пауза 0.55 с
# между разными эндпоинтами приводила к 429 и штрафным Retry-After. Держим общий
# интервал в секунду — запросов немного, зато без штрафных пауз.
MIN_REQUEST_INTERVAL_SEC = 1.05
# Retry-After от 5 секунд Ozon присылает как штраф за всплеск: повтор после него
# снова получает штраф, поэтому не ждём, а сразу отдаём ошибку вызывающему коду —
# у начислений и выкупа есть локальный fallback на financial_data.
RETRY_AFTER_FAIL_FAST_SEC = 5.0
# Финансовые методы после штрафа отпускает не сразу, поэтому долбить их 8 раз
# бессмысленно: держим общий бюджет ожидания, после него — ошибка и локальный
# fallback вызывающего кода.
FINANCE_RETRY_BUDGET_SEC = 12.0
# Сколько фоновый запрос готов ждать пользовательское обновление, прежде чем
# всё-таки уйти в Ozon (иначе планировщик мог бы «залипнуть» навсегда).
BACKGROUND_PRIORITY_WAIT_SEC = 45.0
# Лимит «per second» восстанавливается почти сразу, поэтому долгие паузы между
# повторами только затягивают ответ пользователю (кнопка «Обновить»).
RETRY_BASE_DELAY_SEC = 1.0
RETRY_MAX_DELAY_SEC = 10.0
# Ozon присылает Retry-After=1, но повтор ровно через секунду снова получает 429:
# держим небольшой запас, иначе пачка впустую сжигает попытки.
RETRY_AFTER_BUFFER_SEC = 0.5
THROTTLE_STATE_DIR = os.environ.get("OZON_THROTTLE_DIR") or tempfile.gettempdir()
RATE_LIMIT_MESSAGE = (
    "Превышен лимит запросов к Ozon. Подождите 30–60 секунд и попробуйте снова."
)

RATE_LIMIT_MIN_INTERVAL_SEC = 1.0
RATE_LIMIT_INTERVAL_STEP_SEC = 0.25

# Ozon ограничивает финансовые методы из расчёта «1 запрос в секунду»: держим
# интервал заранее, иначе каждый батч начислений получал 8 отказов 429 подряд.
# По замерам повтор ровно через 1 с снова получает 429, стабильный ответ — с 1.5 с.
KNOWN_PATH_INTERVALS_SEC = {
    "/v1/finance/accrual/postings": 1.6,
    "/v1/finance/products/buyout": 1.6,
}


class OzonRateLimitError(RuntimeError):
    """Ozon не отпустил лимит запросов за все повторы."""


logger = logging.getLogger(__name__)

_throttle_lock = threading.Lock()
_last_request_monotonic: dict[str, float] = {}
_last_path_request_monotonic: dict[str, float] = {}
# Фактический лимит эндпоинта, выученный по 429: часть методов Ozon ограничивает
# из расчёта «1 запрос в секунду», поэтому пачки вызовов упирались в него по 8 раз.
_path_interval_monotonic: dict[str, float] = {}


def _headers(client_id: str, api_key: str) -> dict:
    return {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


_priority_local = threading.local()
_priority_lock = threading.Lock()
_priority_depth = 0


@contextlib.contextmanager
def priority_requests():
    """Пользовательский запрос (кнопка «Обновить») получает лимит Ozon первым.

    Фоновые задания планировщика иначе занимают почти весь бюджет «1 запрос в
    секунду» аккаунта, и обновление из интерфейса ждёт их по 2 секунды на запрос.
    """
    global _priority_depth
    previous = getattr(_priority_local, "active", False)
    _priority_local.active = True
    with _priority_lock:
        _priority_depth += 1
    try:
        yield
    finally:
        with _priority_lock:
            _priority_depth -= 1
        _priority_local.active = previous


def _wait_background_turn() -> None:
    """Фоновый запрос уступает пользовательскому обновлению, но не бесконечно."""
    deadline = time.monotonic() + BACKGROUND_PRIORITY_WAIT_SEC
    while _priority_depth and time.monotonic() < deadline:
        time.sleep(0.2)


def _throttle_state_paths(client_id: str) -> tuple[str, str]:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (client_id or "default"))
    base = os.path.join(THROTTLE_STATE_DIR, f"ozon-throttle-{safe}")
    return f"{base}.lock", f"{base}.json"


@contextlib.contextmanager
def _shared_throttle_state(client_id: str):
    """Состояние троттлинга, общее для всех процессов (веб + планировщик).

    Ozon считает лимит на аккаунт, а не на соединение: без общего состояния два
    процесса одновременно уходят в 429 даже при честных паузах внутри каждого.
    Блокировка файла держится и на время паузы — процессы встают в очередь.
    """
    if fcntl is None:
        yield {}
        return

    lock_path, state_path = _throttle_state_paths(client_id)
    try:
        handle = open(lock_path, "a+")
    except OSError:
        yield {}
        return

    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        state: dict = {}
        try:
            with open(state_path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                state = data
        except (OSError, ValueError):
            state = {}
        try:
            yield state
        finally:
            try:
                with open(state_path, "w", encoding="utf-8") as fh:
                    json.dump(state, fh)
            except OSError:
                logger.debug("Не удалось сохранить состояние троттлинга Ozon", exc_info=True)
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()


def _throttle(client_id: str, path: str = "") -> None:
    """Минимальный интервал между запросами продавца и между вызовами эндпоинта."""
    if not getattr(_priority_local, "active", False):
        _wait_background_turn()
    key = client_id or "_"
    path_key = f"{key}|{path}"
    with _throttle_lock:
        with _shared_throttle_state(client_id) as shared:
            now = time.time()
            shared_paths = shared.get("paths")
            if not isinstance(shared_paths, dict):
                shared_paths = {}
            wait = MIN_REQUEST_INTERVAL_SEC - (now - float(shared.get("last") or 0.0))
            wait = max(
                wait,
                MIN_REQUEST_INTERVAL_SEC - (now - _last_request_monotonic.get(key, 0.0)),
            )
            interval = _path_interval_monotonic.get(
                path_key, KNOWN_PATH_INTERVALS_SEC.get(path, 0.0)
            )
            if interval:
                wait = max(
                    wait,
                    interval - (now - _last_path_request_monotonic.get(path_key, 0.0)),
                )
                if path:
                    wait = max(wait, interval - (now - float(shared_paths.get(path) or 0.0)))
            if wait > 0:
                time.sleep(wait)
            now = time.time()
            _last_request_monotonic[key] = time.monotonic()
            shared["last"] = now
            if path:
                _last_path_request_monotonic[path_key] = time.monotonic()
                shared_paths[path] = now
                shared["paths"] = shared_paths


def _remember_rate_limit(client_id: str, path: str, retry_after: float | None) -> None:
    """Запоминает реальный лимит эндпоинта, чтобы не повторять 429 на каждом вызове."""
    if not path:
        return
    path_key = f"{client_id or '_'}|{path}"
    with _throttle_lock:
        current = _path_interval_monotonic.get(
            path_key, KNOWN_PATH_INTERVALS_SEC.get(path, 0.0)
        )
        interval = max(
            current + RATE_LIMIT_INTERVAL_STEP_SEC,
            retry_after or 0.0,
            RATE_LIMIT_MIN_INTERVAL_SEC,
        )
        _path_interval_monotonic[path_key] = min(RETRY_MAX_DELAY_SEC, interval)


def _relax_rate_limit(client_id: str, path: str) -> None:
    """После успешных запросов постепенно возвращаемся к обычному интервалу."""
    if not path:
        return
    path_key = f"{client_id or '_'}|{path}"
    baseline = KNOWN_PATH_INTERVALS_SEC.get(path, 0.0)
    with _throttle_lock:
        interval = _path_interval_monotonic.get(path_key, 0.0)
        if interval <= baseline:
            _path_interval_monotonic.pop(path_key, None)
            return
        interval = max(baseline, round(interval - RATE_LIMIT_INTERVAL_STEP_SEC, 3))
        if interval <= baseline:
            _path_interval_monotonic.pop(path_key, None)
        else:
            _path_interval_monotonic[path_key] = interval


def _retry_after_seconds(resp: requests.Response) -> float | None:
    """Пауза из заголовка Retry-After (Ozon присылает его вместе с 429)."""
    raw = (resp.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _retry_delay(attempt: int, retry_after: float | None = None) -> float:
    """Задержка перед повтором: пауза Ozon плюс запас, иначе короткая экспонента."""
    if retry_after:
        return min(RETRY_MAX_DELAY_SEC, retry_after + RETRY_AFTER_BUFFER_SEC)
    return min(
        RETRY_MAX_DELAY_SEC,
        RETRY_BASE_DELAY_SEC * (2**attempt) + random.uniform(0.0, 0.5),
    )


def _send(
    client_id: str,
    api_key: str,
    method: str,
    path: str,
    payload: dict | None = None,
) -> requests.Response:
    """Запрос к Ozon с троттлингом и повторами при лимите запросов."""
    last_error: Exception | None = None
    is_finance = path.startswith("/v1/finance/")
    started = time.monotonic()
    for attempt in range(API_MAX_RETRIES):
        _throttle(client_id, path)
        try:
            resp = requests.request(
                method,
                f"{OZON_API_BASE}{path}",
                headers=_headers(client_id, api_key),
                json=payload,
                timeout=60,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Ozon API {path}: сеть — {exc}") from exc

        if resp.status_code == 429:
            retry_after = _retry_after_seconds(resp)
            _remember_rate_limit(client_id, path, retry_after)
            last_error = RuntimeError(
                f"Ozon API {path}: HTTP 429 — {resp.text[:300]}"
            )
            if (
                retry_after
                and retry_after >= RETRY_AFTER_FAIL_FAST_SEC
                and is_finance
            ):
                logger.warning(
                    "Ozon rate limit on %s: Retry-After %.0fs — штраф, повторы прекращаем",
                    path,
                    retry_after,
                )
                raise OzonRateLimitError(RATE_LIMIT_MESSAGE) from last_error
            budget_left = FINANCE_RETRY_BUDGET_SEC - (time.monotonic() - started)
            if attempt >= API_MAX_RETRIES - 1 or (is_finance and budget_left <= 0):
                raise OzonRateLimitError(RATE_LIMIT_MESSAGE) from last_error
            delay = _retry_delay(attempt, retry_after)
            if is_finance:
                delay = min(delay, max(budget_left, RETRY_AFTER_BUFFER_SEC))
            logger.warning(
                "Ozon rate limit on %s (attempt %s/%s), sleep %.1fs: %s",
                path,
                attempt + 1,
                API_MAX_RETRIES,
                delay,
                resp.text[:200],
            )
            time.sleep(delay)
            continue

        if resp.status_code != 200:
            raise RuntimeError(
                f"Ozon API {path}: HTTP {resp.status_code} — {resp.text[:300]}"
            )
        _relax_rate_limit(client_id, path)
        return resp

    if last_error is not None:
        raise OzonRateLimitError(RATE_LIMIT_MESSAGE) from last_error
    raise RuntimeError(f"Ozon API {path}: не удалось выполнить запрос.")


def _request(
    client_id: str,
    api_key: str,
    method: str,
    path: str,
    payload: dict | None = None,
) -> dict:
    return _send(client_id, api_key, method, path, payload).json()


def _post(client_id: str, api_key: str, path: str, payload: dict) -> dict:
    return _request(client_id, api_key, "POST", path, payload)


def _get(client_id: str, api_key: str, path: str) -> dict:
    return _request(client_id, api_key, "GET", path)


def _post_content(client_id: str, api_key: str, path: str, payload: dict) -> bytes:
    """Бинарный ответ Ozon (например, PDF-этикетки отправлений)."""
    return _send(client_id, api_key, "POST", path, payload).content


def check_seller_credentials(client_id: str, api_key: str) -> dict:
    if not client_id or not api_key:
        return {"ok": False, "company_name": None, "error": "Не указаны Client-Id или Api-Key"}
    try:
        data = _post(client_id, api_key, "/v1/seller/info", {})
    except requests.RequestException as exc:
        return {"ok": False, "company_name": None, "error": f"Ошибка сети: {exc}"}
    except RuntimeError as exc:
        if "401" in str(exc) or "403" in str(exc):
            return {"ok": False, "company_name": None, "error": "Неверный Client-Id или Api-Key"}
        return {"ok": False, "company_name": None, "error": str(exc)}

    company = data.get("company") or {}
    name = company.get("name") or company.get("legal_name") or "Организация Ozon"
    return {"ok": True, "company_name": name, "error": None}


def fetch_product_list(client_id: str, api_key: str) -> list[dict]:
    """Список product_id / offer_id (пагинация)."""
    items = []
    last_id = ""
    while True:
        payload = {
            "filter": {"visibility": "ALL"},
            "last_id": last_id,
            "limit": PRODUCT_LIST_LIMIT,
        }
        data = _post(client_id, api_key, "/v3/product/list", payload)
        result = data.get("result") or {}
        batch = result.get("items") or []
        items.extend(batch)
        last_id = result.get("last_id") or ""
        if not last_id or not batch:
            break
    return items


def fetch_products_info(client_id: str, api_key: str, product_ids: list[str]) -> list[dict]:
    """Детальная информация по product_id (пакетами)."""
    all_items = []
    ids = [str(pid) for pid in product_ids if pid]
    for i in range(0, len(ids), INFO_BATCH_SIZE):
        chunk = ids[i : i + INFO_BATCH_SIZE]
        data = _post(
            client_id,
            api_key,
            "/v3/product/info/list",
            {"product_id": chunk},
        )
        all_items.extend(data.get("items") or [])
    return all_items


def _first_image(item: dict) -> str | None:
    primary = item.get("primary_image")
    if isinstance(primary, list) and primary:
        return primary[0]
    if isinstance(primary, str) and primary:
        return primary
    images = item.get("images") or []
    if images:
        return images[0]
    return None


def _first_barcode(item: dict) -> str | None:
    barcodes = item.get("barcodes") or []
    if barcodes:
        return str(barcodes[0])
    return None


def _stock_entries(item: dict) -> list[dict]:
    stocks = item.get("stocks") or {}
    if isinstance(stocks, list):
        return [s for s in stocks if isinstance(s, dict)]
    if isinstance(stocks, dict):
        raw = stocks.get("stocks") or stocks.get("items")
        if isinstance(raw, list):
            return [s for s in raw if isinstance(s, dict)]
        if stocks.get("present") is not None:
            return [stocks]
    return []


def _scheme_key(entry: dict) -> str | None:
    scheme = (entry.get("type") or entry.get("source") or "").strip().lower()
    if not scheme:
        return None
    if "fbo" in scheme:
        return "fbo"
    if "fbs" in scheme or "rfbs" in scheme:
        return "fbs"
    return None


def _stocks_by_scheme(item: dict) -> tuple[int, int]:
    fbo = 0
    fbs = 0
    for entry in _stock_entries(item):
        present = int(entry.get("present", 0) or 0)
        scheme = _scheme_key(entry)
        if scheme == "fbo":
            fbo += present
        elif scheme == "fbs":
            fbs += present
    return fbo, fbs


def normalize_product_item(item: dict) -> dict:
    """Приводим ответ /v3/product/info/list к полям БД."""
    product_id = str(item.get("id") or item.get("product_id") or "")
    price_raw = item.get("price") or item.get("min_price") or "0"
    try:
        price = float(price_raw)
    except (TypeError, ValueError):
        price = 0.0
    stock_fbo, stock_fbs = _stocks_by_scheme(item)
    return {
        "ozon_product_id": product_id,
        "offer_id": str(item.get("offer_id") or ""),
        "barcode": _first_barcode(item),
        "thumbnail_url": _first_image(item),
        "sku": str(item.get("sku") or "") or None,
        "name": str(item.get("name") or "Без названия"),
        "price": price,
        "stock_fbo": stock_fbo,
        "stock_fbs": stock_fbs,
        "raw_data": item,
    }
