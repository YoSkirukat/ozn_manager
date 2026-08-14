"""Общие ключи и нормализация имён для группировки заказов."""

from __future__ import annotations

import re


def product_key(offer_id: str | None, sku: str | None = None) -> str:
    offer = str(offer_id or "").strip()
    if offer and offer != "—":
        return f"offer:{offer}"
    sku_text = str(sku or "").strip()
    if sku_text:
        return f"sku:{sku_text}"
    return "unknown"


def normalize_warehouse_name(name: str | None) -> str:
    if not name:
        return ""
    text = str(name).strip().upper().replace("-", "_").replace(" ", "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text


def normalize_cluster_name(name: str | None) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip()).casefold()
