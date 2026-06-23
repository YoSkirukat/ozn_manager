"""Даты участия товаров в акциях (Ozon API дату не отдаёт — фиксируем при синхронизации)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app

from app.datetime_fmt import format_datetime
from app.models import utcnow

MEMBERSHIP_CACHE_DIR = "promotion_memberships"


def _cache_path(user_id: int) -> Path:
    base = Path(current_app.instance_path) / MEMBERSHIP_CACHE_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / f"user_{user_id}.json"


def _load_memberships(user_id: int) -> dict[str, dict[str, str]]:
    path = _cache_path(user_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {
            str(action_id): {
                str(product_id): str(joined_at)
                for product_id, joined_at in products.items()
                if isinstance(products, dict) and joined_at
            }
            for action_id, products in data.items()
            if isinstance(products, dict)
        }
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _save_memberships(user_id: int, data: dict[str, dict[str, str]]) -> None:
    _cache_path(user_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _parse_stored_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_joined_at_display(value: str | None) -> str:
    return format_datetime(_parse_stored_datetime(value), "%d.%m.%Y")


def sync_promotion_memberships(user_id: int, promotions: list[dict]) -> dict[str, dict[str, str]]:
    """Обновить даты участия и вернуть актуальный кэш."""
    data = _load_memberships(user_id)
    now = utcnow().isoformat().replace("+00:00", "Z")
    current_keys: set[tuple[str, str]] = set()

    for promo in promotions:
        action_id = str(promo.get("action_id") or "").strip()
        if not action_id:
            continue
        bucket = data.setdefault(action_id, {})
        for product in promo.get("products") or []:
            product_id = str(product.get("ozon_product_id") or "").strip()
            if not product_id:
                continue
            current_keys.add((action_id, product_id))
            if product_id not in bucket:
                bucket[product_id] = now

    for action_id in list(data.keys()):
        bucket = data[action_id]
        for product_id in list(bucket.keys()):
            if (action_id, product_id) not in current_keys:
                del bucket[product_id]
        if not bucket:
            del data[action_id]

    _save_memberships(user_id, data)
    return data


def enrich_promotions_with_joined_at(user_id: int, promotions: list[dict]) -> list[dict]:
    memberships = sync_promotion_memberships(user_id, promotions)
    for promo in promotions:
        action_id = str(promo.get("action_id") or "")
        products = []
        for product in promo.get("products") or []:
            product_id = str(product.get("ozon_product_id") or "")
            joined_at = memberships.get(action_id, {}).get(product_id)
            products.append(
                {
                    **product,
                    "joined_at": joined_at,
                    "joined_at_display": format_joined_at_display(joined_at),
                }
            )
        promo["products"] = products
    return promotions


def remove_promotion_membership(user_id: int, action_id, ozon_product_id: str) -> None:
    data = _load_memberships(user_id)
    bucket = data.get(str(action_id))
    if not bucket:
        return
    bucket.pop(str(ozon_product_id), None)
    if not bucket:
        data.pop(str(action_id), None)
    _save_memberships(user_id, data)
