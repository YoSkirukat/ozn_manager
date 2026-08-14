"""Планирование поставки: движение товара по складу или кластеру за период."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from app.datetime_fmt import local_today, utc_bounds_for_local_dates
from app.models import ORDER_STATUS_DELIVERED, Product, Shipment
from app.ozon.stocks import _row_quantity, fetch_stock_rows, group_warehouses
from app.ozon.supplies import fetch_bundle_items
from app.services.stock_report import get_stock_report_cache
from app.services.supply_sync import load_supplies_from_ozon

SUPPLY_RECEIVED_STATUSES = frozenset({
    "ACCEPTED_AT_STORAGE_WAREHOUSE",
    "ACCEPTANCE_AT_STORAGE_WAREHOUSE",
    "REPORTS_FILLING",
    "REPORTS_CONFIRMATION_AWAITING",
    "REPORT_REJECTED",
    "COMPLETED",
})

SCOPE_WAREHOUSE = "warehouse"
SCOPE_CLUSTER = "cluster"
ALL_TARGET = "all"


def normalize_warehouse_name(name: str | None) -> str:
    if not name:
        return ""
    text = str(name).strip().upper().replace("-", "_").replace(" ", "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text


def normalize_cluster_name(name: str | None) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip()).casefold()


def warehouse_names_match(left: str | None, right: str | None) -> bool:
    left_norm = normalize_warehouse_name(left)
    right_norm = normalize_warehouse_name(right)
    return bool(left_norm) and left_norm == right_norm


def _product_key(offer_id: str | None, sku: str | None = None) -> str:
    offer = str(offer_id or "").strip()
    if offer and offer != "—":
        return f"offer:{offer}"
    sku_text = str(sku or "").strip()
    if sku_text:
        return f"sku:{sku_text}"
    return "unknown"


def _normalized_warehouse_set(names: list[str] | set[str] | None) -> set[str] | None:
    if names is None:
        return None
    return {normalize_warehouse_name(name) for name in names if normalize_warehouse_name(name)}


def _warehouse_in_scope(warehouse_name: str | None, allowed_normalized: set[str] | None) -> bool:
    if allowed_normalized is None:
        return True
    return normalize_warehouse_name(warehouse_name) in allowed_normalized


def _iter_cluster_warehouses(clusters: list[dict]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        cluster_name = str(cluster.get("name") or "").strip()
        if not cluster_name:
            continue
        warehouses: list = []
        for logistic in cluster.get("logistic_clusters") or []:
            if isinstance(logistic, dict):
                nested = logistic.get("warehouses") or []
                if isinstance(nested, list):
                    warehouses.extend(nested)
        top = cluster.get("warehouses")
        if isinstance(top, list):
            warehouses.extend(top)
        for warehouse in warehouses:
            if not isinstance(warehouse, dict):
                continue
            warehouse_name = str(warehouse.get("name") or "").strip()
            if warehouse_name:
                pairs.append((cluster_name, warehouse_name))
    return pairs


def _load_cluster_warehouse_map(user) -> dict[str, Any]:
    """Связка складов с кластерами из /v1/cluster/list."""
    warehouse_to_cluster: dict[str, str] = {}
    cluster_warehouses: dict[str, list[str]] = {}
    if not user.has_ozon_credentials():
        return {
            "warehouse_to_cluster": warehouse_to_cluster,
            "cluster_warehouses": cluster_warehouses,
        }
    try:
        from app.services.warehouse_slots import _get_cluster_list_cached

        clusters = _get_cluster_list_cached(user)
    except Exception:
        clusters = []

    for cluster_name, warehouse_name in _iter_cluster_warehouses(clusters):
        key = normalize_warehouse_name(warehouse_name)
        if not key:
            continue
        warehouse_to_cluster.setdefault(key, cluster_name)
        bucket = cluster_warehouses.setdefault(cluster_name, [])
        if warehouse_name not in bucket:
            bucket.append(warehouse_name)

    return {
        "warehouse_to_cluster": warehouse_to_cluster,
        "cluster_warehouses": cluster_warehouses,
    }


def _resolve_cluster_name(name: str, cluster_warehouses: dict[str, list[str]]) -> str | None:
    target = normalize_cluster_name(name)
    if not target:
        return None
    for cluster_name in cluster_warehouses:
        if normalize_cluster_name(cluster_name) == target:
            return cluster_name
    return None


def _cluster_from_order(raw: dict) -> str:
    financial = raw.get("financial_data") if isinstance(raw.get("financial_data"), dict) else {}
    return str(financial.get("cluster_from") or "").strip()


def _order_warehouse_name(raw: dict) -> str:
    analytics = raw.get("analytics_data") if isinstance(raw.get("analytics_data"), dict) else {}
    return str(analytics.get("warehouse_name") or "").strip()


def _order_in_scope(
    raw: dict,
    *,
    allowed_normalized: set[str] | None,
    allowed_cluster_names: set[str] | None,
) -> bool:
    if allowed_normalized is None and not allowed_cluster_names:
        return True
    warehouse_name = _order_warehouse_name(raw)
    if allowed_normalized is not None and _warehouse_in_scope(warehouse_name, allowed_normalized):
        return True
    if allowed_cluster_names:
        cluster_from = normalize_cluster_name(_cluster_from_order(raw))
        if cluster_from and cluster_from in allowed_cluster_names:
            return True
    return False


def _warehouse_stock_rows(rows: list[dict], allowed_normalized: set[str] | None) -> list[dict]:
    items = []
    for row in rows:
        if not _warehouse_in_scope(row.get("warehouse_name"), allowed_normalized):
            continue
        qty = _row_quantity(row)
        if qty <= 0:
            continue
        items.append(
            {
                "sku": str(row.get("sku") or ""),
                "offer_id": str(row.get("item_code") or "—"),
                "name": str(row.get("item_name") or "—"),
                "quantity": qty,
            }
        )
    return items


def _catalog_lookup(user_id: int) -> tuple[dict[str, Product], set[str]]:
    lookup: dict[str, Product] = {}
    primary_keys: set[str] = set()
    for product in Product.query.filter_by(user_id=user_id).all():
        primary_key = _product_key(product.offer_id, product.sku or product.ozon_product_id)
        if primary_key != "unknown":
            primary_keys.add(primary_key)
        if product.offer_id:
            lookup[f"offer:{product.offer_id}"] = product
        if product.sku:
            lookup[f"sku:{product.sku}"] = product
        if product.ozon_product_id:
            lookup[f"sku:{product.ozon_product_id}"] = product
    return lookup, primary_keys


def _resolve_product_meta(
    key: str,
    *,
    catalog: dict[str, Product],
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    product = catalog.get(key)
    fallback = fallback or {}
    offer_id = (
        product.offer_id
        if product and product.offer_id
        else str(fallback.get("offer_id") or "—")
    )
    name = product.name if product else str(fallback.get("name") or "—")
    barcode = product.barcode_display() if product else str(fallback.get("barcode") or "—")
    thumbnail_url = product.thumbnail_url if product and product.thumbnail_url else fallback.get("thumbnail_url")
    profit_markup = None
    profit_markup_negative = False
    if product:
        from app.services.product_profit import scheme_profit_markup, scheme_profit_markup_line

        fbo_data = scheme_profit_markup(product, "fbo")
        fbo_line = scheme_profit_markup_line(product, "fbo")
        if fbo_line:
            profit_markup = fbo_line
            if fbo_data:
                profit_markup_negative = (
                    fbo_data["profit_min"] < 0
                    or fbo_data["profit_max"] < 0
                    or fbo_data["markup_min"] < 0
                    or fbo_data["markup_max"] < 0
                )
    return {
        "offer_id": offer_id or "—",
        "name": name,
        "barcode": barcode,
        "thumbnail_url": thumbnail_url,
        "profit_markup": profit_markup,
        "profit_markup_negative": profit_markup_negative,
    }


def _shipments_in_range(user_id: int, allowed_normalized: set[str] | None, start, end) -> list[Shipment]:
    shipments = (
        Shipment.query.filter(
            Shipment.user_id == user_id,
            Shipment.supply_date >= start,
            Shipment.supply_date <= end,
        )
        .order_by(Shipment.supply_date.asc())
        .all()
    )
    result = []
    for shipment in shipments:
        if shipment.status not in SUPPLY_RECEIVED_STATUSES:
            continue
        if not _warehouse_in_scope(shipment.warehouse_name, allowed_normalized):
            continue
        result.append(shipment)
    return result


def _bundle_ids(shipment: Shipment) -> list[str]:
    raw = shipment.raw_data if isinstance(shipment.raw_data, dict) else {}
    supplies = raw.get("supplies") or []
    bundle_ids: list[str] = []
    for supply in supplies:
        if not isinstance(supply, dict):
            continue
        bundle_id = supply.get("bundle_id")
        if bundle_id and str(bundle_id) not in bundle_ids:
            bundle_ids.append(str(bundle_id))
    return bundle_ids


def _aggregate_incoming(
    user,
    allowed_normalized: set[str] | None,
    date_from: date,
    date_to: date,
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    start, end = utc_bounds_for_local_dates(date_from, date_to)
    shipments = _shipments_in_range(user.id, allowed_normalized, start, end)
    totals: dict[str, int] = defaultdict(int)
    meta: dict[str, dict[str, Any]] = {}

    bundle_cache: dict[str, list[dict]] = {}
    for shipment in shipments:
        for bundle_id in _bundle_ids(shipment):
            if bundle_id not in bundle_cache and user.has_ozon_credentials():
                bundle_cache[bundle_id] = fetch_bundle_items(
                    user.ozon_client_id,
                    user.ozon_api_key,
                    bundle_id,
                )
            for item in bundle_cache.get(bundle_id, []):
                if not isinstance(item, dict):
                    continue
                qty = int(item.get("quantity") or 0)
                if qty <= 0:
                    continue
                key = _product_key(item.get("offer_id"), item.get("sku"))
                totals[key] += qty
                meta[key] = {
                    "offer_id": str(item.get("offer_id") or "—"),
                    "name": str(item.get("name") or "—"),
                    "barcode": str(item.get("barcode") or "—"),
                    "thumbnail_url": item.get("icon_path"),
                }
    return totals, meta


def _aggregate_fbo_orders(
    user_id: int,
    date_from: date,
    date_to: date,
    *,
    allowed_normalized: set[str] | None = None,
    allowed_cluster_names: set[str] | None = None,
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    from app.models import Order

    start, end = utc_bounds_for_local_dates(date_from, date_to)
    orders = (
        Order.query.filter(
            Order.user_id == user_id,
            Order.scheme == "FBO",
            Order.status == ORDER_STATUS_DELIVERED,
            Order.order_date >= start,
            Order.order_date <= end,
        )
        .all()
    )
    totals: dict[str, int] = defaultdict(int)
    meta: dict[str, dict[str, Any]] = {}

    for order in orders:
        raw = order.raw_data if isinstance(order.raw_data, dict) else {}
        if not _order_in_scope(
            raw,
            allowed_normalized=allowed_normalized,
            allowed_cluster_names=allowed_cluster_names,
        ):
            continue
        for item in raw.get("products") or []:
            if not isinstance(item, dict):
                continue
            qty = int(item.get("quantity") or 1)
            if qty <= 0:
                continue
            key = _product_key(item.get("offer_id"), item.get("sku"))
            totals[key] += qty
            meta[key] = {
                "offer_id": str(item.get("offer_id") or "—"),
                "name": str(item.get("name") or "—"),
            }
    return totals, meta


def _aggregate_outgoing(
    user_id: int,
    date_from: date,
    date_to: date,
    *,
    allowed_normalized: set[str] | None = None,
    allowed_cluster_names: set[str] | None = None,
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    return _aggregate_fbo_orders(
        user_id,
        date_from,
        date_to,
        allowed_normalized=allowed_normalized,
        allowed_cluster_names=allowed_cluster_names,
    )


def _aggregate_fbo_stock_all_warehouses(
    stock_rows: list[dict],
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    totals: dict[str, int] = defaultdict(int)
    meta: dict[str, dict[str, Any]] = {}
    for row in stock_rows:
        qty = _row_quantity(row)
        if qty <= 0:
            continue
        key = _product_key(row.get("item_code"), row.get("sku"))
        totals[key] += qty
        meta[key] = {
            "offer_id": str(row.get("item_code") or "—"),
            "name": str(row.get("item_name") or "—"),
        }
    return totals, meta


def _current_stock_map(
    rows: list[dict],
    allowed_normalized: set[str] | None,
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    totals: dict[str, int] = defaultdict(int)
    meta: dict[str, dict[str, Any]] = {}
    for item in _warehouse_stock_rows(rows, allowed_normalized):
        key = _product_key(item.get("offer_id"), item.get("sku"))
        totals[key] += int(item.get("quantity") or 0)
        meta[key] = {
            "offer_id": item.get("offer_id") or "—",
            "name": item.get("name") or "—",
        }
    return totals, meta


def _scope_filters(
    *,
    warehouse_name: str | None,
    cluster_name: str | None,
    mapping: dict[str, Any],
) -> dict[str, Any]:
    cluster_warehouses: dict[str, list[str]] = mapping.get("cluster_warehouses") or {}

    if cluster_name:
        if not cluster_warehouses:
            return {
                "ok": False,
                "error": "Не удалось загрузить список кластеров. Попробуйте позже.",
            }
        if cluster_name == ALL_TARGET:
            all_warehouses: list[str] = []
            for names in cluster_warehouses.values():
                all_warehouses.extend(names)
            return {
                "ok": True,
                "scope": SCOPE_CLUSTER,
                "scope_label": "Кластер",
                "scope_name": "Все кластеры",
                "allowed_normalized": _normalized_warehouse_set(all_warehouses) or set(),
                "allowed_cluster_names": {
                    normalize_cluster_name(name) for name in cluster_warehouses
                },
            }
        resolved = _resolve_cluster_name(cluster_name, cluster_warehouses)
        if not resolved:
            return {"ok": False, "error": "Кластер не найден."}
        warehouses = cluster_warehouses.get(resolved) or []
        return {
            "ok": True,
            "scope": SCOPE_CLUSTER,
            "scope_label": "Кластер",
            "scope_name": resolved,
            "allowed_normalized": _normalized_warehouse_set(warehouses) or set(),
            "allowed_cluster_names": {normalize_cluster_name(resolved)},
        }

    if warehouse_name == ALL_TARGET:
        return {
            "ok": True,
            "scope": SCOPE_WAREHOUSE,
            "scope_label": "Склад",
            "scope_name": "Все склады",
            "allowed_normalized": None,
            "allowed_cluster_names": None,
        }

    if warehouse_name:
        return {
            "ok": True,
            "scope": SCOPE_WAREHOUSE,
            "scope_label": "Склад",
            "scope_name": warehouse_name,
            "allowed_normalized": _normalized_warehouse_set([warehouse_name]) or set(),
            "allowed_cluster_names": None,
        }

    return {"ok": False, "error": "Выберите склад или кластер."}


def build_supply_planning_report(
    user,
    date_from: date,
    date_to: date,
    *,
    warehouse_name: str | None = None,
    cluster_name: str | None = None,
) -> dict:
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле."}
    if not warehouse_name and not cluster_name:
        return {"ok": False, "error": "Выберите склад или кластер."}
    if date_from > date_to:
        return {"ok": False, "error": "Дата начала не может быть позже даты окончания."}
    if (date_to - date_from).days > 365:
        return {"ok": False, "error": "Максимальный период — 365 дней."}

    mapping = _load_cluster_warehouse_map(user)
    scope = _scope_filters(
        warehouse_name=warehouse_name,
        cluster_name=cluster_name,
        mapping=mapping,
    )
    if not scope.get("ok"):
        return {"ok": False, "error": scope.get("error") or "Не удалось определить склад или кластер."}

    allowed_normalized = scope["allowed_normalized"]
    allowed_cluster_names = scope["allowed_cluster_names"]

    sync_to = max(date_to, local_today())
    try:
        load_supplies_from_ozon(user, date_from, sync_to)
    except Exception as exc:
        return {"ok": False, "error": f"Не удалось загрузить поставки: {exc}"}

    try:
        stock_rows = get_stock_report_cache(user.id)
        if stock_rows is None:
            stock_rows = fetch_stock_rows(user.ozon_client_id, user.ozon_api_key)
    except Exception as exc:
        return {"ok": False, "error": f"Не удалось загрузить остатки: {exc}"}

    incoming, incoming_meta = _aggregate_incoming(user, allowed_normalized, date_from, date_to)
    outgoing, outgoing_meta = _aggregate_outgoing(
        user.id,
        date_from,
        date_to,
        allowed_normalized=allowed_normalized,
        allowed_cluster_names=allowed_cluster_names,
    )
    fbo_orders_all, fbo_orders_meta = _aggregate_fbo_orders(user.id, date_from, date_to)
    fbo_stock_all, fbo_stock_meta = _aggregate_fbo_stock_all_warehouses(stock_rows)
    current_stock, stock_meta = _current_stock_map(stock_rows, allowed_normalized)

    today = local_today()
    closing_stock = dict(current_stock)
    if date_to < today:
        after_from = date_to + timedelta(days=1)
        incoming_after, _ = _aggregate_incoming(user, allowed_normalized, after_from, today)
        outgoing_after, _ = _aggregate_outgoing(
            user.id,
            after_from,
            today,
            allowed_normalized=allowed_normalized,
            allowed_cluster_names=allowed_cluster_names,
        )
        for key, qty in incoming_after.items():
            closing_stock[key] = closing_stock.get(key, 0) - qty
        for key, qty in outgoing_after.items():
            closing_stock[key] = closing_stock.get(key, 0) + qty

    all_keys = (
        set(fbo_stock_all)
        | set(fbo_orders_all)
        | set(current_stock)
        | set(incoming)
        | set(outgoing)
        | set(closing_stock)
    )
    catalog, catalog_keys = _catalog_lookup(user.id)
    all_keys |= catalog_keys
    rows: list[dict] = []

    for key in all_keys:
        incoming_qty = int(incoming.get(key, 0))
        outgoing_qty = int(outgoing.get(key, 0))
        closing_qty = int(closing_stock.get(key, 0))
        opening_qty = closing_qty - incoming_qty + outgoing_qty
        fbo_orders_qty = int(fbo_orders_all.get(key, 0))
        fbo_stock_qty = int(fbo_stock_all.get(key, 0))
        if key not in catalog_keys and not any((
            opening_qty,
            incoming_qty,
            outgoing_qty,
            closing_qty,
            fbo_orders_qty,
            fbo_stock_qty,
        )):
            continue

        fallback = (
            incoming_meta.get(key)
            or outgoing_meta.get(key)
            or stock_meta.get(key)
            or fbo_stock_meta.get(key)
            or fbo_orders_meta.get(key)
            or {}
        )
        product = _resolve_product_meta(key, catalog=catalog, fallback=fallback)
        rows.append(
            {
                **product,
                "opening": opening_qty,
                "incoming": incoming_qty,
                "outgoing": outgoing_qty,
                "closing": closing_qty,
                "fbo_orders": fbo_orders_qty,
                "fbo_stock": fbo_stock_qty,
            }
        )

    rows.sort(key=lambda row: (str(row.get("name") or "").lower(), str(row.get("offer_id") or "")))
    scope_name = scope["scope_name"]

    return {
        "ok": True,
        "scope": scope["scope"],
        "scope_label": scope["scope_label"],
        "scope_name": scope_name,
        "warehouse_name": scope_name,
        "date_from": date_from,
        "date_to": date_to,
        "rows": rows,
        "summary": {
            "sku_count": len(rows),
            "opening": sum(row["opening"] for row in rows),
            "incoming": sum(row["incoming"] for row in rows),
            "outgoing": sum(row["outgoing"] for row in rows),
            "closing": sum(row["closing"] for row in rows),
            "fbo_orders": sum(fbo_orders_all.values()),
            "fbo_stock": sum(fbo_stock_all.values()),
        },
    }


def _stock_rows_for_user(user) -> list[dict]:
    rows = get_stock_report_cache(user.id)
    if rows is None and user.has_ozon_credentials():
        try:
            rows = fetch_stock_rows(user.ozon_client_id, user.ozon_api_key)
        except Exception:
            rows = None
    return rows or []


def list_warehouses_with_stock(user) -> list[dict]:
    rows = _stock_rows_for_user(user)
    if not rows:
        return []
    return group_warehouses(rows)


def list_clusters_with_stock(user, stock_rows: list[dict] | None = None) -> list[dict]:
    rows = stock_rows if stock_rows is not None else _stock_rows_for_user(user)
    if not rows:
        return []

    mapping = _load_cluster_warehouse_map(user)
    warehouse_to_cluster = mapping.get("warehouse_to_cluster") or {}
    buckets: dict[str, dict] = {}

    for row in rows:
        qty = _row_quantity(row)
        if qty <= 0:
            continue
        cluster_name = warehouse_to_cluster.get(normalize_warehouse_name(row.get("warehouse_name")))
        if not cluster_name:
            continue
        sku = row.get("sku")
        bucket = buckets.setdefault(
            cluster_name,
            {
                "name": cluster_name,
                "sku_count": 0,
                "total_quantity": 0,
                "_skus": set(),
            },
        )
        if sku is not None:
            bucket["_skus"].add(sku)
        bucket["total_quantity"] += qty

    result = []
    for bucket in buckets.values():
        bucket["sku_count"] = len(bucket.pop("_skus"))
        result.append(bucket)
    result.sort(key=lambda item: (-item["total_quantity"], item["name"].lower()))
    return result


def list_planning_targets(user) -> dict:
    stock_rows = _stock_rows_for_user(user)
    warehouses = group_warehouses(stock_rows) if stock_rows else []
    clusters = list_clusters_with_stock(user, stock_rows)
    return {"warehouses": warehouses, "clusters": clusters}
