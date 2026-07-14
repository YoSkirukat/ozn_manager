"""Обновление остатков FBS в Ozon Seller API."""

from __future__ import annotations

import time

from app.ozon.client import _post

STOCKS_BATCH_SIZE = 100
STOCKS_BATCH_PAUSE_SEC = 0.8


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
        return {"ok": True, "updated": 0, "failed": 0, "errors": []}

    updated = 0
    failed = 0
    errors: list[str] = []

    for start in range(0, len(items), STOCKS_BATCH_SIZE):
        batch = items[start : start + STOCKS_BATCH_SIZE]
        stocks_payload = []
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
                        failed += 1
                        errors.append(f"Некорректный product_id: {product_id}")
                        continue
            elif offer_id:
                entry["offer_id"] = str(offer_id)
            else:
                failed += 1
                errors.append("Нет product_id и offer_id")
                continue
            stocks_payload.append(entry)

        if not stocks_payload:
            continue

        data = _post(client_id, api_key, "/v2/products/stocks", {"stocks": stocks_payload})
        results = data.get("result") or []
        for row in results:
            if not isinstance(row, dict):
                continue
            if row.get("updated"):
                updated += 1
                continue
            failed += 1
            row_errors = row.get("errors") or []
            label = row.get("offer_id") or row.get("product_id") or "?"
            if row_errors:
                messages = []
                for err in row_errors:
                    if isinstance(err, dict):
                        messages.append(str(err.get("message") or err.get("code") or err))
                    else:
                        messages.append(str(err))
                errors.append(f"{label}: {'; '.join(messages)}")
            else:
                errors.append(f"{label}: не обновлён")

        if start + STOCKS_BATCH_SIZE < len(items):
            time.sleep(STOCKS_BATCH_PAUSE_SEC)

    return {
        "ok": failed == 0,
        "updated": updated,
        "failed": failed,
        "errors": errors[:20],
    }
