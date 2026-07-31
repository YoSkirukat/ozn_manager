"""Цены и комиссии товаров (Ozon /v5/product/info/prices, /v1/product/import/prices)."""

from __future__ import annotations

from app.ozon.client import _post

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


def update_product_prices(client_id: str, api_key: str, prices: list[dict]) -> dict:
    """Обновление цен через POST /v1/product/import/prices."""
    if not prices:
        return {"ok": False, "error": "Нет цен для обновления."}

    data = _post(client_id, api_key, "/v1/product/import/prices", {"prices": prices})
    result = data.get("result")
    items = []
    if isinstance(result, list):
        items = result
    elif isinstance(result, dict):
        raw = result.get("items") or result.get("prices") or []
        if isinstance(raw, list):
            items = raw
    elif isinstance(data.get("items"), list):
        items = data["items"]

    errors: list[str] = []
    updated = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("updated") is True:
            updated += 1
            continue
        item_errors = item.get("errors") or []
        if isinstance(item_errors, list) and item_errors:
            for err in item_errors:
                if isinstance(err, dict):
                    msg = str(err.get("message") or err.get("code") or err).strip()
                else:
                    msg = str(err).strip()
                if msg:
                    errors.append(msg)
        elif item.get("updated") is False:
            errors.append("Ozon не принял новую цену.")

    if errors and not updated:
        return {"ok": False, "error": "; ".join(errors[:3]), "items": items}
    if errors:
        return {
            "ok": True,
            "updated": updated,
            "warning": "; ".join(errors[:3]),
            "items": items,
        }
    if items and updated == 0:
        has_any_error = any(isinstance(i, dict) and i.get("errors") for i in items)
        if has_any_error:
            return {"ok": False, "error": "Ozon не принял новую цену.", "items": items}
    return {"ok": True, "updated": updated or len(prices), "items": items}
