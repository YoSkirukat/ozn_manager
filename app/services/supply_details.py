"""Детали заявки на поставку для модального окна."""

from app.datetime_fmt import format_datetime
from app.models import Product, SUPPLY_STATUS_LABELS
from app.services.supply_items import (
    compute_shipment_totals,
    fetch_shipment_items,
)


def _catalog_thumb(user_id: int, offer_id: str | None, sku: str | None) -> str | None:
    if offer_id:
        product = Product.query.filter_by(user_id=user_id, offer_id=str(offer_id)).first()
        if product and product.thumbnail_url:
            return product.thumbnail_url
    if sku:
        text = str(sku)
        product = Product.query.filter_by(user_id=user_id, sku=text).first()
        if product and product.thumbnail_url:
            return product.thumbnail_url
        product = Product.query.filter_by(user_id=user_id, ozon_product_id=text).first()
        if product and product.thumbnail_url:
            return product.thumbnail_url
    return None


def _product_rows(user_id: int, items: list[dict]) -> list[dict]:
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        offer_id = str(item.get("offer_id") or "—")
        thumb = item.get("icon_path") or _catalog_thumb(
            user_id, item.get("offer_id"), item.get("sku")
        )
        rows.append(
            {
                "thumbnail_url": thumb,
                "offer_id": offer_id,
                "name": str(item.get("name") or "—"),
                "barcode": str(item.get("barcode") or "—"),
                "quantity": int(item.get("quantity") or 0),
            }
        )
    return rows


def build_supply_detail(shipment, prefetched: tuple[list[dict], bool] | None = None) -> dict:
    user = shipment.user
    all_items: list[dict] = []
    if prefetched is not None:
        all_items, _ok = prefetched
    elif user:
        all_items, _ok = fetch_shipment_items(user, shipment)

    products = _product_rows(shipment.user_id, all_items)
    sku_count, total_qty = compute_shipment_totals(all_items)

    status_label = SUPPLY_STATUS_LABELS.get(shipment.status, shipment.status)
    supply_date = format_datetime(shipment.supply_date)

    return {
        "ok": True,
        "header": {
            "order_number": shipment.order_number,
            "supply_date": supply_date,
            "status": status_label,
            "status_code": shipment.status,
            "status_class": shipment.status_badge_class(),
            "warehouse_name": shipment.warehouse_name or "—",
            "dropoff_warehouse": shipment.dropoff_warehouse or "—",
            "supplies_count": shipment.supplies_count,
            "items_count": sku_count,
            "total_quantity": total_qty,
        },
        "products": products,
    }


def get_supply_detail(user, shipment_id: int) -> dict:
    from app.extensions import db
    from app.models import Shipment

    shipment = Shipment.query.filter_by(id=shipment_id, user_id=user.id).first()
    if not shipment:
        return {"ok": False, "error": "Поставка не найдена."}

    prefetched = fetch_shipment_items(user, shipment) if user else ([], False)
    items, ok = prefetched
    if ok or items:
        sku_count, units_total = compute_shipment_totals(items)
        shipment.sku_count = sku_count
        shipment.units_total = units_total
        db.session.commit()

    return build_supply_detail(shipment, prefetched)
