"""Товары в заявках на поставку FBO."""

from __future__ import annotations

import time

from app.ozon.supplies import try_fetch_bundle_items

BUNDLE_FETCH_RETRIES = 1
BUNDLE_FETCH_RETRY_DELAY_SEC = 0.35


def bundle_ids_from_raw(raw_data: dict | None) -> list[str]:
    supplies = (raw_data or {}).get("supplies") or []
    bundle_ids: list[str] = []
    for supply in supplies:
        if not isinstance(supply, dict):
            continue
        bundle_id = supply.get("bundle_id")
        if bundle_id and str(bundle_id) not in bundle_ids:
            bundle_ids.append(str(bundle_id))
    return bundle_ids


def bundle_ids_from_shipment(shipment) -> list[str]:
    raw = shipment.raw_data if isinstance(shipment.raw_data, dict) else {}
    return bundle_ids_from_raw(raw)


def _fetch_bundle_with_retries(client_id: str, api_key: str, bundle_id: str) -> tuple[list[dict], bool]:
    last_items: list[dict] = []
    for attempt in range(BUNDLE_FETCH_RETRIES + 1):
        items, ok = try_fetch_bundle_items(client_id, api_key, bundle_id)
        if ok:
            return items, True
        last_items = items
        if attempt < BUNDLE_FETCH_RETRIES:
            time.sleep(BUNDLE_FETCH_RETRY_DELAY_SEC * (attempt + 1))
    return last_items, False


def fetch_bundle_items_cached(
    user,
    bundle_ids: list[str],
    cache: dict[str, tuple[list[dict], bool]] | None = None,
) -> tuple[list[dict], bool]:
    if not user or not user.has_ozon_credentials():
        return [], False

    items: list[dict] = []
    bundle_cache = cache if cache is not None else {}
    all_ok = True

    for bundle_id in bundle_ids:
        cached = bundle_cache.get(bundle_id)
        if cached is None:
            bundle_items, ok = _fetch_bundle_with_retries(
                user.ozon_client_id,
                user.ozon_api_key,
                bundle_id,
            )
            if ok or bundle_items:
                bundle_cache[bundle_id] = (bundle_items, ok)
            cached = (bundle_items, ok)

        bundle_items, ok = cached
        items.extend(bundle_items)
        if not ok:
            all_ok = False

    return items, all_ok


def fetch_shipment_items(
    user,
    shipment,
    cache: dict[str, tuple[list[dict], bool]] | None = None,
) -> tuple[list[dict], bool]:
    bundle_ids = bundle_ids_from_shipment(shipment)
    return fetch_bundle_items_cached(user, bundle_ids, cache)


def _item_sku_key(item: dict) -> str | None:
    for key in ("offer_id", "sku"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def compute_shipment_totals(items: list[dict]) -> tuple[int, int]:
    """Возвращает (число уникальных SKU, суммарное количество единиц)."""
    sku_keys: set[str] = set()
    units = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        units += int(item.get("quantity") or 0)
        sku_key = _item_sku_key(item)
        if sku_key:
            sku_keys.add(sku_key)
    return len(sku_keys), units


def shipment_totals_stale(shipment) -> bool:
    bundle_ids = bundle_ids_from_shipment(shipment)
    if not bundle_ids:
        return False
    if shipment.sku_count is None or shipment.units_total is None:
        return True
    return shipment.sku_count == 0 and shipment.units_total == 0


def refresh_shipment_totals(
    shipment,
    user,
    cache: dict[str, tuple[list[dict], bool]] | None = None,
) -> bool:
    bundle_ids = bundle_ids_from_shipment(shipment)
    if not bundle_ids:
        shipment.sku_count = 0
        shipment.units_total = 0
        return True

    items, ok = fetch_shipment_items(user, shipment, cache)
    if not ok and not items:
        return False

    sku_count, units_total = compute_shipment_totals(items)
    shipment.sku_count = sku_count
    shipment.units_total = units_total
    return True


def ensure_shipments_totals(user, shipments) -> int:
    updates, _has_more = refresh_shipments_totals_batch(user, shipments)
    return len(updates)


def refresh_shipments_totals_batch(
    user,
    shipments,
    *,
    shipment_ids: list[int] | None = None,
    max_items: int = 25,
) -> tuple[list[dict], bool]:
    """Обновляет счётчики товаров; возвращает (изменения, есть ли ещё необновлённые)."""
    if not user or not user.has_ozon_credentials():
        return [], False

    if shipment_ids is not None:
        id_set = {int(x) for x in shipment_ids}
        candidates = [s for s in shipments if s.id in id_set]
    else:
        candidates = list(shipments)

    stale = [shipment for shipment in candidates if shipment_totals_stale(shipment)]
    if not stale:
        return [], False

    cache: dict[str, tuple[list[dict], bool]] = {}
    updates: list[dict] = []
    batch = stale[:max_items]
    for shipment in batch:
        if not refresh_shipment_totals(shipment, user, cache):
            continue
        updates.append(
            {
                "id": shipment.id,
                "sku_count": shipment.sku_count,
                "units_total": shipment.units_total,
            }
        )

    if updates:
        from app.extensions import db

        db.session.commit()

    has_more = len(stale) > len(batch)
    return updates, has_more
