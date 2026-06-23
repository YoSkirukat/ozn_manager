"""Участие товаров в акциях Ozon."""

from __future__ import annotations

from datetime import datetime, timezone

from app.models import Product
from app.ozon.actions import (
    deactivate_action_products,
    fetch_action_products,
    fetch_actions_list,
)
from app.ozon.stocks import group_products
from app.services.promotion_membership import (
    enrich_promotions_with_joined_at,
    remove_promotion_membership,
)


def count_products_in_promotions(user_id: int) -> int:
    """Количество товаров пользователя, участвующих хотя бы в одной акции."""
    count = 0
    for product in Product.query.filter_by(user_id=user_id):
        if product.active_promotions():
            count += 1
    return count


def update_user_products_in_promotions_count(user) -> int:
    """Пересчитать и сохранить счётчик товаров в акциях для пользователя."""
    count = count_products_in_promotions(user.id)
    user.products_in_promotions_count = count
    return count


def _parse_ozon_datetime(value) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_action_active(action: dict, now: datetime) -> bool:
    if not action.get("is_participating"):
        return False
    start = _parse_ozon_datetime(action.get("date_start"))
    end = _parse_ozon_datetime(action.get("date_end"))
    if start and now < start:
        return False
    if end and now > end:
        return False
    count = action.get("participating_products_count")
    if count is not None and int(count or 0) <= 0:
        return False
    return True


def _collect_active_promotions(client_id: str, api_key: str) -> list[dict]:
    """Активные акции и товары в каждой (сырые данные Ozon)."""
    now = datetime.now(timezone.utc)
    actions = fetch_actions_list(client_id, api_key)
    promotions: list[dict] = []

    for action in actions:
        if not _is_action_active(action, now):
            continue
        action_id = action.get("id")
        title = str(action.get("title") or "").strip()
        if action_id is None or not title:
            continue
        try:
            rows = fetch_action_products(client_id, api_key, action_id)
        except Exception:
            rows = []

        product_rows: list[dict] = []
        products: list[dict] = []
        seen_ids: set[str] = set()
        for row in rows:
            pid = _product_id_from_row(row)
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            product_rows.append(row)
            products.append({"ozon_product_id": pid})

        promotions.append(
            {
                "action_id": action_id,
                "title": title,
                "action": action,
                "product_rows": product_rows,
                "products": products,
            }
        )

    return promotions


def promotions_map_from_collected(promotions: list[dict]) -> dict[str, list[str]]:
    """ozon_product_id -> названия активных акций."""
    result: dict[str, list[str]] = {}
    for promo in promotions:
        title = str(promo.get("title") or "").strip()
        if not title:
            continue
        for product in promo.get("products") or []:
            pid = str(product.get("ozon_product_id") or "").strip()
            if not pid:
                continue
            titles = result.setdefault(pid, [])
            if title not in titles:
                titles.append(title)
    return result


def promotion_prices_map_from_collected(promotions: list[dict]) -> dict[str, float]:
    """ozon_product_id -> минимальная акционная цена среди активных акций."""
    result: dict[str, float] = {}
    for promo in promotions:
        for row in promo.get("product_rows") or []:
            pid = _product_id_from_row(row)
            price = _action_price_from_row(row)
            if not pid or price is None:
                continue
            current = result.get(pid)
            if current is None or price < current:
                result[pid] = price
    return result


def _action_price_from_row(row: dict) -> float | None:
    for key in ("action_price", "max_action_price"):
        value = row.get(key)
        if value is None:
            continue
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price > 0:
            return price
    return None


def fetch_product_promotions_data(client_id: str, api_key: str) -> dict:
    collected = _collect_active_promotions(client_id, api_key)
    return {
        "titles": promotions_map_from_collected(collected),
        "prices": promotion_prices_map_from_collected(collected),
    }


def attach_product_sale_prices(
    products: list,
    promo_prices_map: dict[str, float] | None = None,
) -> None:
    """Кэш текущей цены продажи для списка товаров (акционная или обычная)."""
    for product in products:
        promo = product.promotion_price(promo_prices_map)
        if promo is not None:
            product._effective_sale_price = promo
            product._is_promotional_price = True
        else:
            product._effective_sale_price = float(product.price or 0)
            product._is_promotional_price = False


def fetch_product_promotions_map(client_id: str, api_key: str) -> dict[str, list[str]]:
    return fetch_product_promotions_data(client_id, api_key)["titles"]


def sync_promotion_memberships_from_ozon(user) -> dict:
    """Обновить кэш дат участия товаров в акциях по данным Ozon."""
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле."}

    from app.services.promotion_membership import sync_promotion_memberships

    try:
        collected = _collect_active_promotions(user.ozon_client_id, user.ozon_api_key)
        sync_promotion_memberships(user.id, collected)
        unique_products = {
            str(product.get("ozon_product_id") or "").strip()
            for promo in collected
            for product in promo.get("products") or []
            if str(product.get("ozon_product_id") or "").strip()
        }
        return {
            "ok": True,
            "promotion_count": len(collected),
            "product_count": len(unique_products),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _product_id_from_row(row: dict) -> str:
    for key in ("id", "product_id"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _catalog_by_ozon_id(user_id: int) -> dict[str, Product]:
    catalog: dict[str, Product] = {}
    for product in Product.query.filter_by(user_id=user_id).all():
        if product.ozon_product_id:
            catalog[str(product.ozon_product_id)] = product
        if product.sku:
            catalog.setdefault(str(product.sku), product)
    return catalog


def _warehouse_stock_lookup(stock_rows: list[dict]) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for item in group_products(stock_rows):
        total = int(item.get("total_quantity") or 0)
        product_key = str(item.get("product_key") or "")
        if product_key:
            lookup[product_key] = total
        sku = str(item.get("sku") or "").strip()
        if sku:
            lookup[f"sku:{sku}"] = total
        offer_id = str(item.get("offer_id") or "").strip()
        if offer_id and offer_id != "—":
            lookup[f"offer:{offer_id}"] = total
    return lookup


def _warehouse_stock_total(product: dict, catalog: dict[str, Product], lookup: dict[str, int]) -> int | None:
    if not lookup:
        return None

    pid = str(product.get("ozon_product_id") or "").strip()
    keys: list[str] = []
    if pid:
        keys.append(f"sku:{pid}")

    catalog_product = catalog.get(pid)
    if catalog_product:
        if catalog_product.sku:
            keys.append(f"sku:{catalog_product.sku}")
        if catalog_product.ozon_product_id:
            keys.append(f"sku:{catalog_product.ozon_product_id}")
        if catalog_product.offer_id:
            keys.append(f"offer:{catalog_product.offer_id}")

    offer_id = str(product.get("offer_id") or "").strip()
    if offer_id and offer_id != "—":
        keys.append(f"offer:{offer_id}")

    seen: set[str] = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        if key in lookup:
            return lookup[key]
    return 0 if lookup else None


def enrich_promotions_with_warehouse_stock(
    user_id: int,
    promotions: list[dict],
    catalog: dict[str, Product],
) -> list[dict]:
    from app.services.stock_report import get_stock_report_cache

    lookup = _warehouse_stock_lookup(get_stock_report_cache(user_id) or [])
    for promo in promotions:
        for product in promo.get("products") or []:
            total = _warehouse_stock_total(product, catalog, lookup)
            product["warehouse_stock"] = total
            product["warehouse_stock_display"] = "—" if total is None else str(total)
    return promotions


def _product_from_action_row(row: dict, catalog: dict[str, Product]) -> dict:
    pid = _product_id_from_row(row)
    product = catalog.get(pid)
    name = product.name if product else str(row.get("name") or row.get("title") or "—")
    offer_id = product.offer_id if product else str(row.get("offer_id") or "—")
    barcode = (product.barcode if product else row.get("barcode")) or "—"
    return {
        "ozon_product_id": pid,
        "name": name,
        "offer_id": offer_id or "—",
        "barcode": barcode,
        "thumbnail_url": product.thumbnail_url if product else None,
    }


def _format_action_period(action: dict) -> str:
    from app.datetime_fmt import format_datetime

    start = _parse_ozon_datetime(action.get("date_start"))
    end = _parse_ozon_datetime(action.get("date_end"))
    if start and end:
        return f"с {format_datetime(start, '%d.%m.%Y')} по {format_datetime(end, '%d.%m.%Y')}"
    if start:
        return f"с {format_datetime(start, '%d.%m.%Y')}"
    if end:
        return f"до {format_datetime(end, '%d.%m.%Y')}"
    return ""


def build_promotions_report(user) -> dict:
    """Актуальные акции и товары в каждой из них."""
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле.", "promotions": []}

    try:
        catalog = _catalog_by_ozon_id(user.id)
        collected = _collect_active_promotions(user.ozon_client_id, user.ozon_api_key)
        promotions: list[dict] = []

        for item in collected:
            products = [
                _product_from_action_row(row, catalog) for row in item.get("product_rows") or []
            ]
            products.sort(key=lambda product: (product["name"].lower(), product["offer_id"]))
            action = item.get("action") or {}
            promotions.append(
                {
                    "action_id": item["action_id"],
                    "title": item["title"],
                    "period_display": _format_action_period(action),
                    "product_count": len(products),
                    "products": products,
                }
            )

        promotions.sort(key=lambda promo: (-promo["product_count"], promo["title"].lower()))
        enrich_promotions_with_warehouse_stock(user.id, promotions, catalog)
        enrich_promotions_with_joined_at(user.id, promotions)
        unique_products = {
            product["ozon_product_id"]
            for promo in promotions
            for product in promo["products"]
            if product.get("ozon_product_id")
        }

        return {
            "ok": True,
            "promotions": promotions,
            "summary": {
                "promotion_count": len(promotions),
                "product_count": len(unique_products),
            },
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "promotions": []}


def _action_title_by_id(actions: list[dict], action_id: int) -> str | None:
    for action in actions:
        try:
            if int(action.get("id")) == action_id:
                title = str(action.get("title") or "").strip()
                return title or None
        except (TypeError, ValueError):
            continue
    return None


def _update_local_product_promotions(user, ozon_product_id: str, action_title: str | None) -> None:
    if not action_title:
        return

    product = Product.query.filter_by(user_id=user.id, ozon_product_id=str(ozon_product_id)).first()
    if not product:
        product = Product.query.filter_by(user_id=user.id, sku=str(ozon_product_id)).first()
    if not product:
        return

    raw = dict(product.raw_data) if isinstance(product.raw_data, dict) else {}
    promos = raw.get("active_promotions")
    if not isinstance(promos, list):
        return

    new_promos = [title for title in promos if str(title) != action_title]
    if new_promos != promos:
        raw["active_promotions"] = new_promos
        product.raw_data = raw


def remove_product_from_promotion(user, action_id, ozon_product_id: str) -> dict:
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле."}

    pid_text = str(ozon_product_id or "").strip()
    if not pid_text:
        return {"ok": False, "error": "Не указан товар."}

    try:
        action_id_int = int(action_id)
        product_id_int = int(pid_text)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Некорректные параметры запроса."}

    try:
        actions = fetch_actions_list(user.ozon_client_id, user.ozon_api_key)
        action_title = _action_title_by_id(actions, action_id_int)
        result = deactivate_action_products(
            user.ozon_client_id,
            user.ozon_api_key,
            action_id_int,
            [product_id_int],
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    removed_ids = {str(item) for item in (result.get("product_ids") or [])}
    if str(product_id_int) in removed_ids:
        from app.extensions import db

        _update_local_product_promotions(user, pid_text, action_title)
        remove_promotion_membership(user.id, action_id_int, pid_text)
        update_user_products_in_promotions_count(user)
        db.session.commit()
        return {"ok": True, "message": "Товар удалён из акции."}

    for item in result.get("rejected") or []:
        if str(item.get("product_id")) == str(product_id_int):
            reason = str(item.get("reason") or "").strip()
            return {
                "ok": False,
                "error": reason or "Ozon не удалил товар из акции.",
            }

    return {"ok": False, "error": "Не удалось удалить товар из акции."}
