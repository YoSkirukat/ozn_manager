"""Подбор миниатюры заказа из каталога товаров пользователя."""

from app.models import Product


def build_thumbnail_lookup(user_id: int) -> dict[str, str]:
    """Индекс миниатюр каталога: `offer_id`/`sku`/`ozon_product_id` → URL.

    Позволяет не обращаться к БД на каждый заказ при синхронизации списка.
    """
    lookup: dict[str, str] = {}
    for product in Product.query.filter_by(user_id=user_id).all():
        if not product.thumbnail_url:
            continue
        if product.offer_id:
            lookup[f"offer:{product.offer_id}"] = product.thumbnail_url
        if product.sku:
            lookup[f"sku:{product.sku}"] = product.thumbnail_url
        if product.ozon_product_id:
            lookup[f"ozon:{product.ozon_product_id}"] = product.thumbnail_url
    return lookup


def _candidate_keys(raw_data: dict) -> list[str]:
    """Ключи каталога для миниатюры в порядке приоритета (как в старом поиске)."""
    keys: list[str] = []

    posting_product = _first_posting_product(raw_data)
    if posting_product:
        offer_id = posting_product.get("offer_id")
        if offer_id:
            keys.append(f"offer:{offer_id}")
        sku = posting_product.get("sku")
        if sku:
            keys.append(f"sku:{sku}")

    financial = raw_data.get("financial_data")
    if isinstance(financial, dict):
        for item in financial.get("products") or []:
            if not isinstance(item, dict):
                continue
            offer_id = item.get("offer_id")
            if offer_id:
                keys.append(f"offer:{offer_id}")
            for field, prefix in (("sku", "sku"), ("product_id", "ozon")):
                value = item.get(field)
                if value:
                    keys.append(f"{prefix}:{value}")

    return keys


def resolve_thumbnail_url(
    user_id: int,
    raw_data: dict | None,
    lookup: dict[str, str] | None = None,
) -> str | None:
    if not isinstance(raw_data, dict):
        return None

    if lookup is not None:
        for key in _candidate_keys(raw_data):
            url = lookup.get(key)
            if url:
                return url
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
