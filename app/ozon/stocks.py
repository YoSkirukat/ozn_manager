"""Остатки товаров по складам Ozon."""

from app.ozon.client import _post

PAGE_LIMIT = 1000


def fetch_stock_rows(client_id: str, api_key: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0

    while True:
        data = _post(
            client_id,
            api_key,
            "/v2/analytics/stock_on_warehouses",
            {
                "limit": PAGE_LIMIT,
                "offset": offset,
                "warehouse_type": "ALL",
            },
        )
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        batch = result.get("rows") or []
        if not isinstance(batch, list):
            break

        rows.extend(row for row in batch if isinstance(row, dict))

        if len(batch) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT

    return rows


def _row_quantity(row: dict) -> int:
    free_qty = int(row.get("free_to_sell_amount") or 0)
    reserved = int(row.get("reserved_amount") or 0)
    promised = int(row.get("promised_amount") or 0)
    return free_qty + reserved + promised


def group_warehouses(rows: list[dict]) -> list[dict]:
    """Сводка по складам, только где есть остатки."""
    buckets: dict[str, dict] = {}

    for row in rows:
        name = str(row.get("warehouse_name") or "").strip()
        if not name:
            continue

        qty = _row_quantity(row)
        if qty <= 0:
            continue

        free_qty = int(row.get("free_to_sell_amount") or 0)
        reserved = int(row.get("reserved_amount") or 0)
        promised = int(row.get("promised_amount") or 0)
        sku = row.get("sku")

        bucket = buckets.setdefault(
            name,
            {
                "name": name,
                "sku_count": 0,
                "total_quantity": 0,
                "free_to_sell": 0,
                "reserved": 0,
                "promised": 0,
                "_skus": set(),
            },
        )
        if sku is not None:
            bucket["_skus"].add(sku)
        bucket["total_quantity"] += qty
        bucket["free_to_sell"] += free_qty
        bucket["reserved"] += reserved
        bucket["promised"] += promised

    result = []
    for bucket in buckets.values():
        bucket["sku_count"] = len(bucket.pop("_skus"))
        result.append(bucket)

    result.sort(key=lambda x: (-x["total_quantity"], x["name"]))
    return result


def compute_stock_summary(rows: list[dict], warehouses: list[dict] | None = None) -> dict:
    """Сводка: склады и единицы — по группировке, SKU — уникальные по всем складам."""
    if warehouses is None:
        warehouses = group_warehouses(rows)

    unique_skus: set = set()
    for row in rows:
        if _row_quantity(row) <= 0:
            continue
        sku = row.get("sku")
        if sku is not None:
            unique_skus.add(sku)

    return {
        "total_warehouses": len(warehouses),
        "total_sku": len(unique_skus),
        "total_units": sum(w.get("total_quantity", 0) for w in warehouses),
    }


def warehouse_products(rows: list[dict], warehouse_name: str) -> list[dict]:
    items = []
    for row in rows:
        if str(row.get("warehouse_name") or "") != warehouse_name:
            continue
        qty = _row_quantity(row)
        if qty <= 0:
            continue
        items.append(
            {
                "sku": str(row.get("sku") or ""),
                "offer_id": str(row.get("item_code") or "—"),
                "name": str(row.get("item_name") or "—"),
                "free_to_sell": int(row.get("free_to_sell_amount") or 0),
                "reserved": int(row.get("reserved_amount") or 0),
                "promised": int(row.get("promised_amount") or 0),
                "quantity": qty,
            }
        )
    items.sort(key=lambda x: (-x["quantity"], x["name"]))
    return items


def product_row_key(row: dict) -> str:
    sku = row.get("sku")
    if sku is not None and str(sku).strip():
        return f"sku:{sku}"
    code = str(row.get("item_code") or "").strip()
    if code:
        return f"offer:{code}"
    return ""


def group_products(rows: list[dict]) -> list[dict]:
    """Сводка по товарам на всех складах."""
    buckets: dict[str, dict] = {}

    for row in rows:
        key = product_row_key(row)
        if not key:
            continue
        qty = _row_quantity(row)
        if qty <= 0:
            continue

        warehouse_name = str(row.get("warehouse_name") or "").strip()
        bucket = buckets.setdefault(
            key,
            {
                "product_key": key,
                "sku": str(row.get("sku") or ""),
                "offer_id": str(row.get("item_code") or "—"),
                "name": str(row.get("item_name") or "—"),
                "warehouse_count": 0,
                "total_quantity": 0,
                "_warehouses": set(),
            },
        )
        bucket["total_quantity"] += qty
        if warehouse_name:
            bucket["_warehouses"].add(warehouse_name)

    result = []
    for bucket in buckets.values():
        bucket["warehouse_count"] = len(bucket.pop("_warehouses"))
        result.append(bucket)

    result.sort(key=lambda x: (-x["total_quantity"], x["name"].lower()))
    return result


def product_warehouses(rows: list[dict], product_key: str) -> list[dict]:
    """Остатки товара по складам."""
    items = []
    for row in rows:
        if product_row_key(row) != product_key:
            continue
        qty = _row_quantity(row)
        if qty <= 0:
            continue
        items.append(
            {
                "warehouse_name": str(row.get("warehouse_name") or "—"),
                "free_to_sell": int(row.get("free_to_sell_amount") or 0),
                "reserved": int(row.get("reserved_amount") or 0),
                "promised": int(row.get("promised_amount") or 0),
                "quantity": qty,
            }
        )
    items.sort(key=lambda x: (-x["quantity"], x["warehouse_name"]))
    return items
