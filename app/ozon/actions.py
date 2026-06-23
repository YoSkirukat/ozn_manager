"""Акции Ozon Seller API (/v1/actions)."""

from __future__ import annotations

from app.ozon.client import _get, _post

ACTION_PRODUCTS_LIMIT = 1000


def fetch_actions_list(client_id: str, api_key: str) -> list[dict]:
    """Список акций, доступных продавцу."""
    data = _get(client_id, api_key, "/v1/actions")
    result = data.get("result")
    if not isinstance(result, list):
        return []
    return [row for row in result if isinstance(row, dict)]


def fetch_action_products(client_id: str, api_key: str, action_id: int | str) -> list[dict]:
    """Товары, участвующие в акции (пагинация last_id)."""
    items: list[dict] = []
    last_id: str | int | None = None
    while True:
        payload: dict = {
            "action_id": int(action_id),
            "limit": ACTION_PRODUCTS_LIMIT,
        }
        if last_id not in (None, ""):
            payload["last_id"] = last_id
        data = _post(client_id, api_key, "/v1/actions/products", payload)
        result = data.get("result") or {}
        batch = result.get("products") or []
        if not isinstance(batch, list):
            batch = []
        items.extend(row for row in batch if isinstance(row, dict))
        new_last_id = result.get("last_id")
        if not batch or new_last_id in (None, "") or new_last_id == last_id:
            break
        last_id = new_last_id
    return items


def deactivate_action_products(
    client_id: str,
    api_key: str,
    action_id: int | str,
    product_ids: list[int | str],
) -> dict:
    """Удалить товары из акции."""
    ids: list[int] = []
    for product_id in product_ids:
        try:
            ids.append(int(product_id))
        except (TypeError, ValueError):
            continue
    if not ids:
        return {"product_ids": [], "rejected": []}

    data = _post(
        client_id,
        api_key,
        "/v1/actions/products/deactivate",
        {
            "action_id": int(action_id),
            "product_ids": ids,
        },
    )
    result = data.get("result") or {}
    return {
        "product_ids": result.get("product_ids") or [],
        "rejected": result.get("rejected") or [],
    }
