"""Загрузка возвратов FBO/FBS/rFBS из Ozon Seller API."""

from datetime import date, datetime, time, timezone

from app.ozon.client import _post

RETURNS_LIST_LIMIT = 500


def _iso_range(date_from: date, date_to: date) -> tuple[str, str]:
    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    end = datetime.combine(date_to, time.max.replace(microsecond=0), tzinfo=timezone.utc)
    return start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), end.strftime("%Y-%m-%dT%H:%M:%S.999Z")


def _parse_last_id(row: dict) -> int:
    raw_id = row.get("id") or row.get("return_id")
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return 0


def _fetch_v1_returns(
    client_id: str,
    api_key: str,
    date_from: date,
    date_to: date,
    return_schema: str,
) -> list[dict]:
    time_from, time_to = _iso_range(date_from, date_to)
    items: list[dict] = []
    last_id = 0

    while True:
        payload = {
            "filter": {
                "visual_status_change_moment": {
                    "time_from": time_from,
                    "time_to": time_to,
                },
                "return_schema": return_schema,
            },
            "limit": RETURNS_LIST_LIMIT,
            "last_id": last_id,
        }
        data = _post(client_id, api_key, "/v1/returns/list", payload)
        batch = [row for row in (data.get("returns") or []) if isinstance(row, dict)]
        items.extend(batch)

        if not data.get("has_next") or not batch:
            break

        next_last_id = 0
        for row in reversed(batch):
            next_last_id = _parse_last_id(row)
            if next_last_id:
                break
        if not next_last_id or next_last_id == last_id:
            break
        last_id = next_last_id

    return items


def _extract_rfbs_rows(data: dict) -> list[dict]:
    if not isinstance(data, dict):
        return []

    candidates: list = []
    returns = data.get("returns")
    if isinstance(returns, list):
        candidates = returns
    elif isinstance(returns, dict):
        if returns.get("return_id") is not None or returns.get("return_number"):
            return [returns]
        for key in ("items", "return_list", "list"):
            nested = returns.get(key)
            if isinstance(nested, list):
                candidates = nested
                break

    result = data.get("result")
    if not candidates and isinstance(result, dict):
        nested_returns = result.get("returns")
        if isinstance(nested_returns, list):
            candidates = nested_returns
        elif isinstance(nested_returns, dict):
            if nested_returns.get("return_id") is not None or nested_returns.get("return_number"):
                return [nested_returns]
            for key in ("items", "return_list", "list"):
                nested = nested_returns.get(key)
                if isinstance(nested, list):
                    candidates = nested
                    break

    return [row for row in candidates if isinstance(row, dict)]


def _fetch_rfbs_returns(
    client_id: str,
    api_key: str,
    date_from: date,
    date_to: date,
) -> list[dict]:
    time_from, time_to = _iso_range(date_from, date_to)
    items: list[dict] = []
    last_id: int | None = None

    while True:
        payload: dict = {
            "filter": {
                "created_at": {
                    "from": time_from,
                    "to": time_to,
                },
                "group_state": ["All"],
            },
            "limit": RETURNS_LIST_LIMIT,
        }
        if last_id is not None:
            payload["last_id"] = last_id

        try:
            data = _post(client_id, api_key, "/v2/returns/rfbs/list", payload)
        except RuntimeError:
            break

        batch = _extract_rfbs_rows(data)
        for row in batch:
            row["_return_source"] = "rfbs"
        items.extend(batch)

        if len(batch) < RETURNS_LIST_LIMIT:
            break

        next_last_id = 0
        for row in reversed(batch):
            next_last_id = _parse_last_id(row)
            if next_last_id:
                break
        if not next_last_id or next_last_id == last_id:
            break
        last_id = next_last_id

    return items


def fetch_rfbs_return(client_id: str, api_key: str, return_id: int) -> dict | None:
    try:
        data = _post(client_id, api_key, "/v2/returns/rfbs/get", {"return_id": int(return_id)})
    except RuntimeError:
        return None

    if not isinstance(data, dict):
        return None

    returns = data.get("returns")
    if isinstance(returns, dict):
        return returns
    if isinstance(returns, list) and returns and isinstance(returns[0], dict):
        return returns[0]

    result = data.get("result")
    if isinstance(result, dict):
        nested = result.get("returns")
        if isinstance(nested, dict):
            return nested
        if isinstance(nested, list) and nested and isinstance(nested[0], dict):
            return nested[0]

    if data.get("return_id") is not None:
        return data
    return None


def fetch_returns_list(
    client_id: str,
    api_key: str,
    date_from: date,
    date_to: date,
) -> list[dict]:
    """Список возвратов FBO, FBS и rFBS за период."""
    merged: list[dict] = []
    seen_keys: set[str] = set()

    for schema in ("FBO", "FBS"):
        for row in _fetch_v1_returns(client_id, api_key, date_from, date_to, schema):
            key = f"v1:{row.get('id')}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            row["_return_source"] = "v1"
            merged.append(row)

    for row in _fetch_rfbs_returns(client_id, api_key, date_from, date_to):
        key = f"rfbs:{row.get('return_id') or row.get('id')}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        merged.append(row)

    return merged
