"""Заявки на поставку FBO (supply-order) из Ozon Seller API."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from app.ozon.client import _post

LIST_LIMIT = 100
GET_BATCH_SIZE = 50
BUNDLE_LIMIT = 100

# Строковые коды статусов для /v3/supply-order/list
DEFAULT_SUPPLY_ORDER_STATES: tuple[str, ...] = (
    "ORDER_STATE_DATA_FILLING",
    "ORDER_STATE_READY_TO_SUPPLY",
    "ORDER_STATE_ACCEPTED_AT_SUPPLY_WAREHOUSE",
    "ORDER_STATE_IN_TRANSIT",
    "ORDER_STATE_ACCEPTED_AT_STORAGE_WAREHOUSE",
    "ORDER_STATE_ACCEPTANCE_AT_STORAGE_WAREHOUSE",
    "ORDER_STATE_REPORTS_FILLING",
    "ORDER_STATE_REPORTS_CONFIRMATION_AWAITING",
    "ORDER_STATE_REPORT_REJECTED",
    "ORDER_STATE_COMPLETED",
    "ORDER_STATE_CANCELLED",
    "ORDER_STATE_REJECTED_AT_SUPPLY_WAREHOUSE",
)

# Числовые коды (запасной вариант для старых ответов API)
NUMERIC_STATE_CODES = list(range(1, 12))


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _normalize_api_state(state: str | None) -> str:
    text = str(state or "unknown").strip()
    if text.startswith("ORDER_STATE_"):
        return text.removeprefix("ORDER_STATE_")
    return text


def _iso_date_range(date_from: date, date_to: date) -> tuple[str, str, str, str]:
    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    end = datetime.combine(date_to, time.max.replace(microsecond=0), tzinfo=timezone.utc)
    iso_start = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    iso_end = end.strftime("%Y-%m-%dT%H:%M:%S.999Z")
    return date_from.isoformat(), date_to.isoformat(), iso_start, iso_end


def _fetch_states_from_counter(client_id: str, api_key: str) -> list[str]:
    try:
        data = _post(client_id, api_key, "/v1/supply-order/status/counter", {})
    except RuntimeError:
        return list(DEFAULT_SUPPLY_ORDER_STATES)

    states: list[str] = []
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        state = str(item.get("order_state") or "").strip()
        if state:
            states.append(state)
    return states or list(DEFAULT_SUPPLY_ORDER_STATES)


def _list_supply_order_ids_for_filter(
    client_id: str,
    api_key: str,
    state,
    filter_extra: dict,
) -> list[int]:
    order_ids: list[int] = []
    last_id = ""

    while True:
        payload = {
            "filter": {"states": [state], **filter_extra},
            "last_id": last_id,
            "limit": LIST_LIMIT,
            "sort_by": 1,
            "sort_dir": 2,
        }
        try:
            data = _post(client_id, api_key, "/v3/supply-order/list", payload)
        except RuntimeError:
            break

        batch = data.get("order_ids") or []
        if isinstance(batch, list):
            order_ids.extend(int(x) for x in batch if x is not None)
        new_last = data.get("last_id") or ""
        if not new_last or not batch:
            break
        last_id = str(new_last)

    return order_ids


def _list_supply_order_ids(
    client_id: str,
    api_key: str,
    date_from: date,
    date_to: date,
) -> list[int]:
    """Собирает id заявок по всем статусам (дата поставки и дата создания)."""
    delivery_from, delivery_to, created_from, created_to = _iso_date_range(date_from, date_to)
    seen: set[int] = set()

    states = _fetch_states_from_counter(client_id, api_key)
    date_filters = (
        {"delivery_date_from": delivery_from, "delivery_date_to": delivery_to},
        {"created_date_from": created_from, "created_date_to": created_to},
    )

    for state in states:
        for filter_extra in date_filters:
            for oid in _list_supply_order_ids_for_filter(
                client_id, api_key, state, filter_extra
            ):
                seen.add(oid)

    # Запасной проход по числовым кодам (если строковые статусы не вернули часть заявок)
    for state_code in NUMERIC_STATE_CODES:
        for filter_extra in date_filters:
            for oid in _list_supply_order_ids_for_filter(
                client_id, api_key, state_code, filter_extra
            ):
                seen.add(oid)

    return list(seen)


def fetch_bundle_items(client_id: str, api_key: str, bundle_id: str) -> list[dict]:
    items, _ok = try_fetch_bundle_items(client_id, api_key, bundle_id)
    return items


def try_fetch_bundle_items(client_id: str, api_key: str, bundle_id: str) -> tuple[list[dict], bool]:
    if not bundle_id:
        return [], True

    items: list[dict] = []
    last_id = ""

    while True:
        try:
            data = _post(
                client_id,
                api_key,
                "/v1/supply-order/bundle",
                {
                    "bundle_ids": [bundle_id],
                    "limit": BUNDLE_LIMIT,
                    "last_id": last_id,
                },
            )
        except RuntimeError:
            return items, False

        batch = data.get("items") or []
        items.extend(item for item in batch if isinstance(item, dict))
        new_last = data.get("last_id") or ""
        if not new_last or not batch:
            break
        last_id = str(new_last)

    return items, True


def _fetch_supply_orders_batch(client_id: str, api_key: str, order_ids: list[int]) -> list[dict]:
    if not order_ids:
        return []
    data = _post(
        client_id,
        api_key,
        "/v3/supply-order/get",
        {"order_ids": [str(oid) for oid in order_ids]},
    )
    orders = data.get("orders") or []
    return [o for o in orders if isinstance(o, dict)]


def normalize_supply_order(order: dict) -> dict | None:
    if not isinstance(order, dict):
        return None

    ozon_id = order.get("order_id")
    if ozon_id is None:
        return None

    order_number = str(order.get("order_number") or ozon_id)
    state = _normalize_api_state(order.get("state"))

    timeslot = order.get("timeslot") if isinstance(order.get("timeslot"), dict) else {}
    slot = timeslot.get("timeslot") if isinstance(timeslot.get("timeslot"), dict) else {}
    supply_date = _parse_datetime(slot.get("from")) or _parse_datetime(order.get("created_date"))
    if supply_date is None:
        supply_date = datetime.now(timezone.utc)

    dropoff = order.get("drop_off_warehouse") if isinstance(order.get("drop_off_warehouse"), dict) else {}
    dropoff_name = str(dropoff.get("name") or "") or None

    supplies = order.get("supplies") or []
    warehouse_name = None
    if supplies and isinstance(supplies[0], dict):
        storage = supplies[0].get("storage_warehouse")
        if isinstance(storage, dict):
            warehouse_name = str(storage.get("name") or "") or None

    return {
        "ozon_supply_id": str(ozon_id),
        "order_number": order_number,
        "status": state,
        "supply_date": supply_date,
        "warehouse_name": warehouse_name,
        "dropoff_warehouse": dropoff_name,
        "supplies_count": len(supplies) if isinstance(supplies, list) else 0,
        "raw_data": order,
    }


def fetch_supply_orders(client_id: str, api_key: str, date_from: date, date_to: date) -> list[dict]:
    """Список заявок на поставку за период (по дате поставки)."""
    order_ids = _list_supply_order_ids(client_id, api_key, date_from, date_to)
    items: list[dict] = []

    for i in range(0, len(order_ids), GET_BATCH_SIZE):
        chunk = order_ids[i : i + GET_BATCH_SIZE]
        for order in _fetch_supply_orders_batch(client_id, api_key, chunk):
            normalized = normalize_supply_order(order)
            if normalized:
                items.append(normalized)

    items.sort(key=lambda x: x["supply_date"], reverse=True)
    return items
