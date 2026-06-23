"""Цены и комиссии товаров (Ozon /v5/product/info/prices)."""

from __future__ import annotations

from app.ozon.client import INFO_BATCH_SIZE, _post

PRICES_LIMIT = 1000


def _parse_prices_payload(data: dict) -> tuple[list[dict], str]:
    items = data.get("items")
    cursor = data.get("cursor") or ""
    if items is None:
        result = data.get("result")
        if isinstance(result, dict):
            items = result.get("items")
            cursor = result.get("cursor") or cursor
    if not isinstance(items, list):
        items = []
    return items, str(cursor or "")


def fetch_products_prices(client_id: str, api_key: str, product_ids: list[str]) -> list[dict]:
    """Комиссии и цены по product_id (пакетами до 1000)."""
    all_items: list[dict] = []
    ids = [str(pid) for pid in product_ids if pid]
    if not ids:
        return all_items

    for offset in range(0, len(ids), PRICES_LIMIT):
        chunk = ids[offset : offset + PRICES_LIMIT]
        cursor = ""
        while True:
            payload = {
                "filter": {"product_id": chunk},
                "limit": min(len(chunk), PRICES_LIMIT),
            }
            if cursor:
                payload["cursor"] = cursor
            data = _post(client_id, api_key, "/v5/product/info/prices", payload)
            batch, cursor = _parse_prices_payload(data)
            all_items.extend(batch)
            if not cursor:
                break
    return all_items
