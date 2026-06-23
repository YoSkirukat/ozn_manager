"""Клиент Ozon Seller API."""

import requests

OZON_API_BASE = "https://api-seller.ozon.ru"
PRODUCT_LIST_LIMIT = 1000
INFO_BATCH_SIZE = 100


def _headers(client_id: str, api_key: str) -> dict:
    return {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


def _request(client_id: str, api_key: str, method: str, path: str, payload: dict | None = None) -> dict:
    resp = requests.request(
        method,
        f"{OZON_API_BASE}{path}",
        headers=_headers(client_id, api_key),
        json=payload,
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Ozon API {path}: HTTP {resp.status_code} — {resp.text[:300]}")
    return resp.json()


def _post(client_id: str, api_key: str, path: str, payload: dict) -> dict:
    return _request(client_id, api_key, "POST", path, payload)


def _get(client_id: str, api_key: str, path: str) -> dict:
    return _request(client_id, api_key, "GET", path)


def check_seller_credentials(client_id: str, api_key: str) -> dict:
    if not client_id or not api_key:
        return {"ok": False, "company_name": None, "error": "Не указаны Client-Id или Api-Key"}
    try:
        data = _post(client_id, api_key, "/v1/seller/info", {})
    except requests.RequestException as exc:
        return {"ok": False, "company_name": None, "error": f"Ошибка сети: {exc}"}
    except RuntimeError as exc:
        if "401" in str(exc) or "403" in str(exc):
            return {"ok": False, "company_name": None, "error": "Неверный Client-Id или Api-Key"}
        return {"ok": False, "company_name": None, "error": str(exc)}

    company = data.get("company") or {}
    name = company.get("name") or company.get("legal_name") or "Организация Ozon"
    return {"ok": True, "company_name": name, "error": None}


def fetch_product_list(client_id: str, api_key: str) -> list[dict]:
    """Список product_id / offer_id (пагинация)."""
    items = []
    last_id = ""
    while True:
        payload = {
            "filter": {"visibility": "ALL"},
            "last_id": last_id,
            "limit": PRODUCT_LIST_LIMIT,
        }
        data = _post(client_id, api_key, "/v3/product/list", payload)
        result = data.get("result") or {}
        batch = result.get("items") or []
        items.extend(batch)
        last_id = result.get("last_id") or ""
        if not last_id or not batch:
            break
    return items


def fetch_products_info(client_id: str, api_key: str, product_ids: list[str]) -> list[dict]:
    """Детальная информация по product_id (пакетами)."""
    all_items = []
    ids = [str(pid) for pid in product_ids if pid]
    for i in range(0, len(ids), INFO_BATCH_SIZE):
        chunk = ids[i : i + INFO_BATCH_SIZE]
        data = _post(
            client_id,
            api_key,
            "/v3/product/info/list",
            {"product_id": chunk},
        )
        all_items.extend(data.get("items") or [])
    return all_items


def _first_image(item: dict) -> str | None:
    primary = item.get("primary_image")
    if isinstance(primary, list) and primary:
        return primary[0]
    if isinstance(primary, str) and primary:
        return primary
    images = item.get("images") or []
    if images:
        return images[0]
    return None


def _first_barcode(item: dict) -> str | None:
    barcodes = item.get("barcodes") or []
    if barcodes:
        return str(barcodes[0])
    return None


def _stock_entries(item: dict) -> list[dict]:
    stocks = item.get("stocks") or {}
    if isinstance(stocks, list):
        return [s for s in stocks if isinstance(s, dict)]
    if isinstance(stocks, dict):
        raw = stocks.get("stocks") or stocks.get("items")
        if isinstance(raw, list):
            return [s for s in raw if isinstance(s, dict)]
        if stocks.get("present") is not None:
            return [stocks]
    return []


def _scheme_key(entry: dict) -> str | None:
    scheme = (entry.get("type") or entry.get("source") or "").strip().lower()
    if not scheme:
        return None
    if "fbo" in scheme:
        return "fbo"
    if "fbs" in scheme or "rfbs" in scheme:
        return "fbs"
    return None


def _stocks_by_scheme(item: dict) -> tuple[int, int]:
    fbo = 0
    fbs = 0
    for entry in _stock_entries(item):
        present = int(entry.get("present", 0) or 0)
        scheme = _scheme_key(entry)
        if scheme == "fbo":
            fbo += present
        elif scheme == "fbs":
            fbs += present
    return fbo, fbs


def normalize_product_item(item: dict) -> dict:
    """Приводим ответ /v3/product/info/list к полям БД."""
    product_id = str(item.get("id") or item.get("product_id") or "")
    price_raw = item.get("price") or item.get("min_price") or "0"
    try:
        price = float(price_raw)
    except (TypeError, ValueError):
        price = 0.0
    stock_fbo, stock_fbs = _stocks_by_scheme(item)
    return {
        "ozon_product_id": product_id,
        "offer_id": str(item.get("offer_id") or ""),
        "barcode": _first_barcode(item),
        "thumbnail_url": _first_image(item),
        "sku": str(item.get("sku") or "") or None,
        "name": str(item.get("name") or "Без названия"),
        "price": price,
        "stock_fbo": stock_fbo,
        "stock_fbs": stock_fbs,
        "raw_data": item,
    }
