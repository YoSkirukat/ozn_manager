"""Отчёт «Остатки товаров» по складам."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app

from app.models import Product
from app.ozon.stocks import (
    compute_stock_summary,
    fetch_stock_rows,
    group_products,
    group_warehouses,
    product_warehouses,
    warehouse_products,
)

STOCK_CACHE_DIR = "stock_cache"


def _enrich_thumbnails(user_id: int, products: list[dict]) -> list[dict]:
    for item in products:
        thumb = None
        barcode = None
        offer_id = item.get("offer_id")
        sku = item.get("sku")
        product = None
        if offer_id and offer_id != "—":
            product = Product.query.filter_by(user_id=user_id, offer_id=str(offer_id)).first()
        if not product and sku:
            product = Product.query.filter_by(user_id=user_id, sku=str(sku)).first()
        if not product and sku:
            product = Product.query.filter_by(user_id=user_id, ozon_product_id=str(sku)).first()
        if product:
            if product.thumbnail_url:
                thumb = product.thumbnail_url
            if product.barcode:
                barcode = product.barcode
        item["thumbnail_url"] = thumb
        item["barcode"] = barcode or "—"
    return products


def enrich_product_stock_list(user_id: int, products: list[dict]) -> list[dict]:
    return _enrich_thumbnails(user_id, products)


def _cache_path(user_id: int) -> Path:
    base = Path(current_app.instance_path) / STOCK_CACHE_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / f"user_{user_id}.json"


def save_stock_report_cache(user_id: int, rows: list[dict]) -> None:
    """Серверный кэш остатков (для регламентного задания и страницы отчёта)."""
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
    }
    _cache_path(user_id).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _read_stock_cache_payload(user_id: int) -> dict | None:
    path = _cache_path(user_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def get_stock_report_cache(user_id: int) -> list[dict] | None:
    data = _read_stock_cache_payload(user_id)
    if not data:
        return None
    rows = data.get("rows")
    return rows if isinstance(rows, list) else None


def get_stock_report_updated_at(user_id: int) -> datetime | None:
    """UTC-время последней загрузки остатков из кэша."""
    data = _read_stock_cache_payload(user_id)
    if not data:
        return None
    raw = data.get("updated_at")
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_stock_report(user) -> dict:
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле."}

    try:
        rows = fetch_stock_rows(user.ozon_client_id, user.ozon_api_key)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    warehouses = group_warehouses(rows)
    summary = compute_stock_summary(rows, warehouses)
    return {
        "ok": True,
        "warehouses": warehouses,
        "rows": rows,
        "summary": summary,
        "message": (
            f"Складов: {summary['total_warehouses']}, "
            f"SKU: {summary['total_sku']}, "
            f"единиц: {summary['total_units']}."
        ),
    }


def get_warehouse_stock_detail(user, warehouse_name: str, cached_rows: list[dict] | None = None) -> dict:
    if not warehouse_name:
        return {"ok": False, "error": "Не указан склад."}

    if cached_rows is None:
        cached_rows = get_stock_report_cache(user.id)
    if cached_rows is None:
        if not user.has_ozon_credentials():
            return {"ok": False, "error": "Подключите Ozon API в профиле."}
        try:
            cached_rows = fetch_stock_rows(user.ozon_client_id, user.ozon_api_key)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    products = _enrich_thumbnails(user.id, warehouse_products(cached_rows, warehouse_name))
    if not products:
        return {"ok": False, "error": "На этом складе нет остатков."}

    total_qty = sum(p["quantity"] for p in products)
    return {
        "ok": True,
        "header": {
            "warehouse_name": warehouse_name,
            "sku_count": len(products),
            "total_quantity": total_qty,
        },
        "products": products,
    }


def get_product_stock_detail(user, product_key: str, cached_rows: list[dict] | None = None) -> dict:
    if not product_key:
        return {"ok": False, "error": "Не указан товар."}

    if cached_rows is None:
        cached_rows = get_stock_report_cache(user.id)
    if cached_rows is None:
        if not user.has_ozon_credentials():
            return {"ok": False, "error": "Подключите Ozon API в профиле."}
        try:
            cached_rows = fetch_stock_rows(user.ozon_client_id, user.ozon_api_key)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    warehouses = product_warehouses(cached_rows, product_key)
    if not warehouses:
        return {"ok": False, "error": "Товар не найден на складах."}

    product_info = next(
        (item for item in group_products(cached_rows) if item.get("product_key") == product_key),
        None,
    )
    if not product_info:
        return {"ok": False, "error": "Товар не найден."}

    product_info = enrich_product_stock_list(user.id, [dict(product_info)])[0]
    total_qty = sum(item["quantity"] for item in warehouses)

    return {
        "ok": True,
        "header": {
            "name": product_info.get("name") or "—",
            "offer_id": product_info.get("offer_id") or "—",
            "barcode": product_info.get("barcode") or "—",
            "thumbnail_url": product_info.get("thumbnail_url"),
            "warehouse_count": len(warehouses),
            "total_quantity": total_qty,
        },
        "warehouses": warehouses,
    }
