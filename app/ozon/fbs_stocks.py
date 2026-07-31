"""Обновление остатков FBS в Ozon Seller API."""

from __future__ import annotations

import logging
import time

from app.ozon.client import _post

logger = logging.getLogger(__name__)

STOCKS_BATCH_SIZE = 100
STOCKS_BATCH_PAUSE_SEC = 1.2
TOO_FREQUENT_RETRY_DELAY_SEC = 65.0
TOO_FREQUENT_MARKERS = (
    "too frequently",
    "stock_update_too_frequently",
    "stocks_update_too_frequently",
)


def fetch_fbs_warehouses(client_id: str, api_key: str) -> list[dict]:
    """Список FBS/rFBS складов продавца (/v2/warehouse/list)."""
    warehouses: list[dict] = []
    cursor = ""
    while True:
        payload: dict = {"limit": 100}
        if cursor:
            payload["cursor"] = cursor
        data = _post(client_id, api_key, "/v2/warehouse/list", payload)
        rows = data.get("warehouses")
        if rows is None:
            rows = data.get("result") or []
        if isinstance(rows, dict):
            rows = rows.get("warehouses") or []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            warehouse_id = row.get("warehouse_id")
            if warehouse_id is None:
                continue
            status = str(row.get("status") or "").strip().lower()
            if status == "disabled":
                continue
            warehouses.append(
                {
                    "warehouse_id": int(warehouse_id),
                    "name": str(row.get("name") or f"Склад {warehouse_id}"),
                    "status": status or "created",
                }
            )
        if not data.get("has_next"):
            break
        cursor = str(data.get("cursor") or "").strip()
        if not cursor:
            break
    return warehouses


def resolve_fbs_warehouse_id(client_id: str, api_key: str, preferred_id: int | None = None) -> int:
    # Если склад задан в профиле — не дергаем список, сразу используем его.
    if preferred_id is not None:
        return preferred_id

    warehouses = fetch_fbs_warehouses(client_id, api_key)
    if not warehouses:
        raise RuntimeError(
            "В Ozon не найдено ни одного FBS-склада. "
            "Укажите warehouse_id в профиле (поле «Склад FBS»)."
        )

    if len(warehouses) == 1:
        return warehouses[0]["warehouse_id"]

    names = ", ".join(f"{w['name']} ({w['warehouse_id']})" for w in warehouses)
    raise RuntimeError(
        "У кабинета несколько FBS-складов. Укажите warehouse_id в профиле "
        f"(поле «Склад FBS») или оставьте один активный склад. Найдены: {names}."
    )


def _item_key(item: dict) -> str:
    offer_id = item.get("offer_id")
    if offer_id not in (None, ""):
        return f"offer:{offer_id}"
    product_id = item.get("product_id")
    if product_id not in (None, ""):
        return f"product:{product_id}"
    return ""


def _is_too_frequent_message(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in TOO_FREQUENT_MARKERS)


def _row_error_messages(row: dict) -> list[str]:
    messages: list[str] = []
    for err in row.get("errors") or []:
        if isinstance(err, dict):
            messages.append(str(err.get("message") or err.get("code") or err))
        else:
            messages.append(str(err))
    return messages


def _send_stocks_batch(
    client_id: str,
    api_key: str,
    warehouse_id: int,
    batch: list[dict],
) -> tuple[list[dict], list[dict], list[str]]:
    """Отправляет один батч. Возвращает (успешные items, too_frequent items, прочие ошибки)."""
    stocks_payload = []
    prepared: list[dict] = []
    hard_errors: list[str] = []

    for item in batch:
        entry: dict = {
            "warehouse_id": int(warehouse_id),
            "stock": int(item["stock"]),
        }
        product_id = item.get("product_id")
        offer_id = item.get("offer_id")
        if product_id not in (None, ""):
            try:
                entry["product_id"] = int(product_id)
            except (TypeError, ValueError):
                if offer_id:
                    entry["offer_id"] = str(offer_id)
                else:
                    hard_errors.append(f"Некорректный product_id: {product_id}")
                    continue
        elif offer_id:
            entry["offer_id"] = str(offer_id)
        else:
            hard_errors.append("Нет product_id и offer_id")
            continue
        stocks_payload.append(entry)
        prepared.append(item)

    if not stocks_payload:
        return [], [], hard_errors

    data = _post(client_id, api_key, "/v2/products/stocks", {"stocks": stocks_payload})
    results = data.get("result") or []

    by_key = {_item_key(item): item for item in prepared if _item_key(item)}
    updated_items: list[dict] = []
    too_frequent_items: list[dict] = []

    for idx, row in enumerate(results):
        if not isinstance(row, dict):
            continue
        label = row.get("offer_id") or row.get("product_id") or "?"
        key = ""
        if row.get("offer_id") not in (None, ""):
            key = f"offer:{row.get('offer_id')}"
        elif row.get("product_id") not in (None, ""):
            key = f"product:{row.get('product_id')}"
        item = by_key.get(key)
        if item is None and idx < len(prepared):
            item = prepared[idx]

        if row.get("updated"):
            if item is not None:
                updated_items.append(item)
            continue

        messages = _row_error_messages(row)
        joined = "; ".join(messages) if messages else "не обновлён"
        if messages and all(_is_too_frequent_message(m) for m in messages):
            if item is not None:
                too_frequent_items.append(item)
            hard_errors.append(f"{label}: {joined}")
        else:
            hard_errors.append(f"{label}: {joined}")

    return updated_items, too_frequent_items, hard_errors


def _push_stocks(
    client_id: str,
    api_key: str,
    warehouse_id: int,
    items: list[dict],
) -> tuple[list[dict], list[dict], list[str]]:
    updated_items: list[dict] = []
    too_frequent_items: list[dict] = []
    errors: list[str] = []

    for start in range(0, len(items), STOCKS_BATCH_SIZE):
        batch = items[start : start + STOCKS_BATCH_SIZE]
        batch_updated, batch_frequent, batch_errors = _send_stocks_batch(
            client_id, api_key, warehouse_id, batch
        )
        updated_items.extend(batch_updated)
        too_frequent_items.extend(batch_frequent)
        errors.extend(batch_errors)
        if start + STOCKS_BATCH_SIZE < len(items):
            time.sleep(STOCKS_BATCH_PAUSE_SEC)

    return updated_items, too_frequent_items, errors


def update_fbs_stocks(
    client_id: str,
    api_key: str,
    warehouse_id: int,
    items: list[dict],
) -> dict:
    """Массовое обновление остатков через /v2/products/stocks.

    items: [{product_id|offer_id, stock}, ...]
    """
    if not items:
        return {
            "ok": True,
            "updated": 0,
            "failed": 0,
            "deferred": 0,
            "errors": [],
            "updated_items": [],
        }

    updated_items, too_frequent_items, errors = _push_stocks(
        client_id, api_key, warehouse_id, items
    )

    # Повтор через ~1 мин для SKU, отклонённых из‑за частоты обновлений.
    if too_frequent_items:
        logger.info(
            "FBS stocks: %s SKU rejected as too frequent, retry in %.0fs",
            len(too_frequent_items),
            TOO_FREQUENT_RETRY_DELAY_SEC,
        )
        time.sleep(TOO_FREQUENT_RETRY_DELAY_SEC)
        retry_updated, still_frequent, retry_errors = _push_stocks(
            client_id, api_key, warehouse_id, too_frequent_items
        )
        updated_items.extend(retry_updated)
        too_frequent_items = still_frequent
        # Убираем старые сообщения too frequent, оставляем финальные.
        errors = [e for e in errors if not _is_too_frequent_message(e)]
        errors.extend(retry_errors)

    hard_failed = len(errors) - sum(1 for e in errors if _is_too_frequent_message(e))
    deferred = len(too_frequent_items)
    # Считаем «жёсткими» только ошибки не про частоту; частота — отложенный повтор.
    failed = hard_failed + deferred
    only_deferred = failed > 0 and hard_failed == 0

    return {
        "ok": failed == 0 or only_deferred,
        "updated": len(updated_items),
        "failed": failed,
        "deferred": deferred,
        "errors": errors[:20],
        "updated_items": updated_items,
        "only_deferred": only_deferred,
    }
