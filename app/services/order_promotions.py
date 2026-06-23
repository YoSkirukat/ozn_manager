"""Пометки о покупке товаров по акции в заказах."""

from __future__ import annotations

from app.ozon.actions import fetch_actions_list
from app.services.order_details import (
    _financial_products,
    _posting_products,
)

PROMOTION_RAW_KEY = "_product_promotions"
PROMOTIONS_FILTER_VERSION = 2

# В financial_data.actions Ozon передаёт не только акции продавца, но и скидки
# маркетплейса, округление и системные корректировки — их не показываем.
_EXCLUDED_ACTION_SUBSTRINGS = (
    "округление",
    "системная виртуальная скидка",
    "скидка (за счет озон)",
    "скидка (за счёт озон)",
    "скидка за счет озон",
    "скидка за счёт озон",
    "by ai benefit",
    "ai benefit system",
)


def fetch_known_promotion_titles(client_id: str, api_key: str) -> set[str]:
    """Названия акций из кабинета продавца (/v1/actions)."""
    try:
        actions = fetch_actions_list(client_id, api_key)
    except Exception:
        return set()
    return {str(row.get("title") or "").strip() for row in actions if row.get("title")}


def product_line_key(posting_item: dict, fin_item: dict | None, index: int) -> str:
    offer_id = posting_item.get("offer_id")
    if offer_id:
        return f"offer:{offer_id}"
    for src in (fin_item or {}, posting_item):
        for field, prefix in (("sku", "sku"), ("product_id", "ozon")):
            value = src.get(field)
            if value is not None and str(value).strip():
                return f"{prefix}:{value}"
    return f"line:{index}"


def _normalize_titles(values) -> list[str]:
    if not isinstance(values, list):
        return []
    titles: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in titles:
            titles.append(text)
    return titles


def _is_excluded_action_title(title: str) -> bool:
    lower = title.lower().strip()
    if not lower or lower == "скидка":
        return True
    return any(pattern in lower for pattern in _EXCLUDED_ACTION_SUBSTRINGS)


def _matches_known_promotion(title: str, known_titles: set[str]) -> bool:
    if not known_titles:
        return True
    normalized = title.strip()
    if not normalized:
        return False
    lower = normalized.lower()
    for known in known_titles:
        known_lower = known.lower()
        if lower == known_lower or known_lower in lower or lower in known_lower:
            return True
    return False


def filter_seller_promotion_titles(
    titles: list[str],
    known_titles: set[str] | None = None,
) -> list[str]:
    """Оставляет только акции продавца, как в ЛК Ozon."""
    known = known_titles or set()
    result: list[str] = []
    for title in titles:
        text = str(title).strip()
        if not text or _is_excluded_action_title(text):
            continue
        if not _matches_known_promotion(text, known):
            continue
        if text not in result:
            result.append(text)
    return result


def promotions_from_financial(
    fin_item: dict | None,
    *,
    known_titles: set[str] | None = None,
) -> dict:
    """Акции продавца из financial_data.products[].actions."""
    fin = fin_item if isinstance(fin_item, dict) else {}
    titles = filter_seller_promotion_titles(
        _normalize_titles(fin.get("actions")),
        known_titles,
    )
    return {
        "in_promotion": bool(titles),
        "titles": titles,
        "source": "ozon_financial",
    }


def _read_snapshot(raw: dict | None) -> dict[str, dict]:
    if not isinstance(raw, dict):
        return {}
    snapshot = raw.get(PROMOTION_RAW_KEY)
    if not isinstance(snapshot, dict):
        return {}
    return {str(key): dict(value) for key, value in snapshot.items() if isinstance(value, dict)}


def _snapshot_needs_refresh(raw: dict) -> bool:
    return raw.get("_product_promotions_version") != PROMOTIONS_FILTER_VERSION


def promotion_info_for_line(
    raw: dict | None,
    posting_item: dict,
    fin_item: dict | None,
    index: int,
) -> dict:
    snapshot = _read_snapshot(raw)
    key = product_line_key(posting_item, fin_item, index)
    info = snapshot.get(key)
    if isinstance(info, dict) and info.get("in_promotion"):
        return {
            "in_promotion": True,
            "titles": _normalize_titles(info.get("titles")),
            "source": info.get("source"),
        }
    return {
        "in_promotion": False,
        "titles": [],
        "source": info.get("source") if isinstance(info, dict) else None,
    }


def apply_product_promotions(
    order,
    *,
    user_id: int | None = None,
    known_titles: set[str] | None = None,
    force_refresh: bool = False,
) -> bool:
    """Обновляет снимок акций в raw_data заказа. Возвращает True, если данные изменились."""
    raw = order.raw_data if isinstance(order.raw_data, dict) else {}
    if not raw:
        return False

    if not force_refresh and not _snapshot_needs_refresh(raw):
        snapshot = _read_snapshot(raw)
        if snapshot and all(
            isinstance(value, dict) and value.get("source") == "ozon_financial"
            for value in snapshot.values()
        ):
            return False

    posting_items = _posting_products(raw)
    if not posting_items:
        return False

    financial_items = _financial_products(raw)
    snapshot: dict[str, dict] = {}
    changed = False

    for idx, posting_item in enumerate(posting_items):
        fin_item = financial_items[idx] if idx < len(financial_items) else {}
        key = product_line_key(posting_item, fin_item, idx)
        entry = promotions_from_financial(fin_item, known_titles=known_titles)
        snapshot[key] = entry
        previous = _read_snapshot(raw).get(key)
        if previous != entry:
            changed = True

    if changed or _snapshot_needs_refresh(raw):
        order.raw_data = {
            **raw,
            PROMOTION_RAW_KEY: snapshot,
            "_product_promotions_version": PROMOTIONS_FILTER_VERSION,
        }
        return True
    return False


def apply_product_promotions_batch(
    orders: list,
    user_id: int,
    user=None,
    *,
    known_titles: set[str] | None = None,
) -> int:
    if not orders:
        return 0

    updated = 0
    for order in orders:
        raw = order.raw_data if isinstance(order.raw_data, dict) else {}
        force = _snapshot_needs_refresh(raw)
        if apply_product_promotions(
            order,
            user_id=user_id,
            known_titles=known_titles,
            force_refresh=force,
        ):
            updated += 1
    return updated


def promotion_info_for_primary_product(order) -> dict:
    raw = order.raw_data if isinstance(order.raw_data, dict) else {}
    posting_items = _posting_products(raw)
    if not posting_items:
        return {"in_promotion": False, "titles": []}

    financial_items = _financial_products(raw)
    fin_item = financial_items[0] if financial_items else {}
    return promotion_info_for_line(raw, posting_items[0], fin_item, 0)
