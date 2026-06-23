"""Подбор миниатюры заказа из каталога товаров пользователя."""

from app.models import Product


def resolve_thumbnail_url(user_id: int, raw_data: dict | None) -> str | None:
    if not isinstance(raw_data, dict):
        return None

    posting_product = _first_posting_product(raw_data)
    if posting_product:
        url = _lookup_catalog(user_id, posting_product)
        if url:
            return url

    financial = raw_data.get("financial_data")
    if isinstance(financial, dict):
        for item in financial.get("products") or []:
            if isinstance(item, dict):
                url = _lookup_catalog(user_id, item, use_product_id=True)
                if url:
                    return url

    return None


def _first_posting_product(raw_data: dict) -> dict | None:
    products = raw_data.get("products") or []
    for item in products:
        if isinstance(item, dict):
            return item
    return None


def _lookup_catalog(user_id: int, data: dict, use_product_id: bool = False) -> str | None:
    offer_id = data.get("offer_id")
    if offer_id:
        product = Product.query.filter_by(user_id=user_id, offer_id=str(offer_id)).first()
        if product and product.thumbnail_url:
            return product.thumbnail_url

    keys = ("sku", "product_id") if use_product_id else ("sku",)
    for key in keys:
        value = data.get(key)
        if not value:
            continue
        text = str(value)
        product = Product.query.filter_by(user_id=user_id, sku=text).first()
        if product and product.thumbnail_url:
            return product.thumbnail_url
        product = Product.query.filter_by(user_id=user_id, ozon_product_id=text).first()
        if product and product.thumbnail_url:
            return product.thumbnail_url

    return None
