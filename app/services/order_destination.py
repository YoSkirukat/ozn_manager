"""Определение страны доставки заказа по данным Ozon."""

from __future__ import annotations

from app.models import HOME_COUNTRY_NAME

# Валюта оплаты покупателем → страна (EAEU / СНГ).
CURRENCY_TO_COUNTRY: dict[str, str] = {
    "BYN": "Беларусь",
    "KZT": "Казахстан",
    "UZS": "Узбекистан",
    "KGS": "Кыргызстан",
    "AMD": "Армения",
    "GEL": "Грузия",
    "TJS": "Таджикистан",
    "AZN": "Азербайджан",
}

# Кластер доставки Ozon (часто город или страна) → страна.
CLUSTER_TO_COUNTRY: dict[str, str] = {
    "беларусь": "Беларусь",
    "казахстан": "Казахстан",
    "узбекистан": "Узбекистан",
    "кыргызстан": "Кыргызстан",
    "армения": "Армения",
    "грузия": "Грузия",
    "астана": "Казахстан",
    "алматы": "Казахстан",
    "шымкент": "Казахстан",
    "караганда": "Казахстан",
    "актобе": "Казахстан",
    "минск": "Беларусь",
    "гомель": "Беларусь",
    "брест": "Беларусь",
    "витебск": "Беларусь",
    "могилёв": "Беларусь",
    "могилев": "Беларусь",
    "ташкент": "Узбекистан",
    "самарканд": "Узбекистан",
    "бишкек": "Кыргызстан",
    "ош": "Кыргызстан",
    "ереван": "Армения",
    "тбилиси": "Грузия",
}

# Подстроки в названии кластера (если точного совпадения нет).
CLUSTER_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("беларус", "Беларусь"),
    ("belarus", "Беларусь"),
    ("казах", "Казахстан"),
    ("kazakh", "Казахстан"),
    ("узбек", "Узбекистан"),
    ("uzbek", "Узбекистан"),
    ("кыргыз", "Кыргызстан"),
    ("kyrgyz", "Кыргызстан"),
    ("армен", "Армения"),
    ("armen", "Армения"),
    ("груз", "Грузия"),
    ("georg", "Грузия"),
    ("таджик", "Таджикистан"),
    ("tajik", "Таджикистан"),
    ("азербайдж", "Азербайджан"),
    ("azerbaij", "Азербайджан"),
)

# Англоязычные и альтернативные названия стран в полях адреса.
COUNTRY_NAME_ALIASES: dict[str, str] = {
    "russia": HOME_COUNTRY_NAME,
    "россия": HOME_COUNTRY_NAME,
    "рф": HOME_COUNTRY_NAME,
    "belarus": "Беларусь",
    "беларусь": "Беларусь",
    "белоруссия": "Беларусь",
    "kazakhstan": "Казахстан",
    "казахстан": "Казахстан",
    "uzbekistan": "Узбекистан",
    "узбекистан": "Узбекистан",
    "kyrgyzstan": "Кыргызстан",
    "кыргызстан": "Кыргызстан",
    "киргизия": "Кыргызстан",
    "armenia": "Армения",
    "армения": "Армения",
    "georgia": "Грузия",
    "грузия": "Грузия",
}


def _normalize_country_name(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    mapped = COUNTRY_NAME_ALIASES.get(text.lower())
    return mapped or text


def _country_from_currency_code(code: str | None) -> str | None:
    if not code:
        return None
    upper = str(code).strip().upper()
    if not upper or upper == "RUB":
        return None
    return CURRENCY_TO_COUNTRY.get(upper)


def _country_from_cluster(cluster_to: str | None) -> str | None:
    if not cluster_to or not isinstance(cluster_to, str):
        return None
    text = cluster_to.strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in CLUSTER_TO_COUNTRY:
        return CLUSTER_TO_COUNTRY[lowered]
    for keyword, country in CLUSTER_KEYWORDS:
        if keyword in lowered:
            return country
    return None


def _financial_products(raw: dict) -> list[dict]:
    financial = raw.get("financial_data")
    if isinstance(financial, dict):
        items = financial.get("products") or []
        return [p for p in items if isinstance(p, dict)]
    if isinstance(financial, list):
        return [p for p in financial if isinstance(p, dict)]
    return []


def _country_from_financial_products(raw: dict) -> str | None:
    for product in _financial_products(raw):
        for key in ("customer_currency_code", "currency_code"):
            country = _country_from_currency_code(product.get(key))
            if country:
                return country
    return None


def _country_from_address_blocks(raw: dict) -> str | None:
    for src in (raw.get("delivery_method"), raw.get("addressee"), raw.get("customer")):
        if not isinstance(src, dict):
            continue
        for key in ("country", "country_name", "country_code"):
            country = _normalize_country_name(str(src.get(key) or ""))
            if country and country != HOME_COUNTRY_NAME:
                return country
    return None


def _country_from_analytics(raw: dict) -> str | None:
    analytics = raw.get("analytics_data")
    if not isinstance(analytics, dict):
        return None
    for key in ("region", "city", "delivery_type"):
        value = analytics.get(key)
        if isinstance(value, str):
            country = _country_from_cluster(value)
            if country:
                return country
    return None


def resolve_delivery_country(raw: dict | None) -> str:
    """Страна доставки: не Россия для заказов за рубеж."""
    if not isinstance(raw, dict):
        return HOME_COUNTRY_NAME

    for resolver in (
        _country_from_address_blocks,
        _country_from_financial_products,
        _country_from_analytics,
    ):
        country = resolver(raw)
        if country:
            return country

    financial = raw.get("financial_data")
    if isinstance(financial, dict):
        country = _country_from_cluster(str(financial.get("cluster_to") or ""))
        if country:
            return country

    return HOME_COUNTRY_NAME


def is_international_delivery(raw: dict | None) -> bool:
    country = resolve_delivery_country(raw)
    return bool(country and country.lower() != HOME_COUNTRY_NAME.lower())
