"""Склады FBO и таймслоты поставки (Ozon Seller API)."""

from __future__ import annotations

import random
import threading
import time
from datetime import date, timedelta

from app.ozon.client import _post

SUPPLY_TYPE_DIRECT = 2
DELETION_SKU_MODE_DEFAULT = 1
API_MAX_RETRIES = 8
MIN_REQUEST_INTERVAL_SEC = 1.25
DRAFT_INFO_INITIAL_DELAY_SEC = 3.0
DRAFT_INFO_POLL_DELAY_SEC = 4.0
DRAFT_INFO_MAX_ATTEMPTS = 10
RATE_LIMIT_MESSAGE = (
    "Превышен лимит запросов к Ozon. Подождите 30–60 секунд и попробуйте снова."
)
UNAVAILABLE_WAREHOUSE_SLOTS_MESSAGE = (
    "Таймслоты для этого склада недоступны. Выберите склад со статусом «Доступен»."
)

_throttle_lock = threading.Lock()
_last_request_monotonic: dict[str, float] = {}


def friendly_ozon_error(exc: Exception) -> str:
    text = str(exc)
    if "HTTP 429" in text:
        return RATE_LIMIT_MESSAGE
    if "HTTP 404" in text and (
        "warehouse scoring result" in text
        or "/v2/draft/timeslot/info" in text
    ):
        return UNAVAILABLE_WAREHOUSE_SLOTS_MESSAGE
    if text.startswith("Ozon API "):
        return text
    return text


def _throttle(client_id: str, path: str) -> None:
    key = f"{client_id}:{path}"
    with _throttle_lock:
        now = time.monotonic()
        last = _last_request_monotonic.get(key, 0.0)
        wait = MIN_REQUEST_INTERVAL_SEC - (now - last)
        if wait > 0:
            time.sleep(wait)
        _last_request_monotonic[key] = time.monotonic()


def _post_retry(client_id: str, api_key: str, path: str, payload: dict) -> dict:
    last_error: Exception | None = None
    for attempt in range(API_MAX_RETRIES):
        _throttle(client_id, path)
        try:
            return _post(client_id, api_key, path, payload)
        except RuntimeError as exc:
            last_error = exc
            if "HTTP 429" not in str(exc):
                raise
            if attempt >= API_MAX_RETRIES - 1:
                raise RuntimeError(RATE_LIMIT_MESSAGE) from exc
            delay = min(32.0, 3.0 * (2 ** attempt) + random.uniform(0.0, 1.5))
            time.sleep(delay)
    if last_error:
        raise RuntimeError(friendly_ozon_error(last_error))
    raise RuntimeError("Не удалось выполнить запрос к Ozon API.")


def fetch_cluster_list(client_id: str, api_key: str) -> list[dict]:
    data = _post_retry(
        client_id,
        api_key,
        "/v1/cluster/list",
        {"cluster_type": "CLUSTER_TYPE_OZON"},
    )
    clusters = data.get("clusters") or []
    return [item for item in clusters if isinstance(item, dict)]


def create_direct_draft(
    client_id: str,
    api_key: str,
    *,
    sku: int,
    macrolocal_cluster_id: int,
    cluster_id: int,
    storage_warehouse_id: int,
) -> int:
    payload = {
        "items": [{"sku": int(sku), "quantity": 1}],
        "deletion_sku_mode": DELETION_SKU_MODE_DEFAULT,
        "cluster_info": {
            "macrolocal_cluster_id": int(macrolocal_cluster_id),
            "items": [
                {
                    "cluster_id": int(cluster_id),
                    "warehouse_id": int(storage_warehouse_id),
                    "sku": int(sku),
                    "quantity": 1,
                }
            ],
        },
    }
    data = _post_retry(client_id, api_key, "/v1/draft/direct/create", payload)
    draft_id = data.get("draft_id")
    if draft_id is None:
        raise RuntimeError("Ozon API не вернул draft_id.")
    return int(draft_id)


def fetch_draft_info(client_id: str, api_key: str, draft_id: int) -> dict:
    return _post_retry(
        client_id,
        api_key,
        "/v2/draft/create/info",
        {"draft_id": int(draft_id)},
    )


def wait_for_draft_info(
    client_id: str,
    api_key: str,
    draft_id: int,
    *,
    attempts: int = DRAFT_INFO_MAX_ATTEMPTS,
    initial_delay_sec: float = DRAFT_INFO_INITIAL_DELAY_SEC,
    poll_delay_sec: float = DRAFT_INFO_POLL_DELAY_SEC,
) -> dict:
    if initial_delay_sec > 0:
        time.sleep(initial_delay_sec)

    last_info: dict = {}
    for attempt in range(attempts):
        info = fetch_draft_info(client_id, api_key, draft_id)
        last_info = info if isinstance(info, dict) else {}
        status = str(last_info.get("status") or "").strip().upper()
        clusters = last_info.get("clusters") or []
        if status in {"SUCCESS", "CALCULATION_STATUS_SUCCESS"} and clusters:
            return last_info
        if status in {"FAILED", "CALCULATION_STATUS_FAILED"}:
            errors = last_info.get("errors") or []
            message = "; ".join(str(item) for item in errors if item) or "Ozon не смог рассчитать черновик."
            raise RuntimeError(message)
        if attempt < attempts - 1:
            time.sleep(poll_delay_sec)
    return last_info


def fetch_draft_timeslots(
    client_id: str,
    api_key: str,
    *,
    draft_id: int,
    macrolocal_cluster_id: int,
    cluster_id: int,
    storage_warehouse_id: int,
    date_from: date,
    date_to: date,
) -> dict:
    payload = {
        "draft_id": int(draft_id),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "supply_type": SUPPLY_TYPE_DIRECT,
        "selected_cluster_warehouses": [
            {
                "storage_warehouse_id": int(storage_warehouse_id),
                "cluster_id": int(cluster_id),
                "macrolocal_cluster_id": int(macrolocal_cluster_id),
            }
        ],
    }
    return _post_retry(client_id, api_key, "/v2/draft/timeslot/info", payload)


def default_timeslot_period(days: int = 14) -> tuple[date, date]:
    today = date.today()
    return today, today + timedelta(days=max(1, days) - 1)
