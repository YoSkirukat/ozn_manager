"""Детальная информация о заказе для модального окна."""

from decimal import Decimal

from app.datetime_fmt import format_datetime
from app.db_sqlite import db_session_commit
from app.extensions import db
from app.models import LABEL_DOWNLOADED_RAW_KEY, ORDER_STATUS_DELIVERED, ORDER_STATUS_LABELS, Product
from app.ozon.client import _post
from app.ozon.finance import (
    PostingAccruals,
    _parse_operation_date,
    accrual_amount,
    load_posting_accruals,
)
from app.services.order_buyout import (
    BUYOUT_RAW_CACHE_KEYS,
    apply_buyout_to_products,
    build_buyout_index_for_orders,
    clear_buyout_cache,
    _cached_buyout_amount,
)
from app.services.order_returns import (
    detect_financial_refund,
    order_has_financial_refund,
    order_has_refund_after_delivery,
    persist_financial_refund_cache,
    refund_after_delivery_tooltip,
)
from app.services.order_images import resolve_thumbnail_url


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal(0)


def _money(value) -> float:
    return float(_decimal(value).quantize(Decimal("0.01")))


def fetch_posting_detail(user, posting_number: str, scheme: str) -> dict | None:
    if not user.has_ozon_credentials():
        return None
    path = "/v3/posting/fbs/get" if scheme.upper() == "FBS" else "/v2/posting/fbo/get"
    try:
        data = _post(
            user.ozon_client_id,
            user.ozon_api_key,
            path,
            {
                "posting_number": posting_number,
                "with": {"financial_data": True, "analytics_data": True},
            },
        )
        result = data.get("result")
        return result if isinstance(result, dict) else None
    except Exception:
        return None


def _posting_products(raw: dict) -> list[dict]:
    products = raw.get("products") or []
    return [p for p in products if isinstance(p, dict)]


def _financial_products(raw: dict) -> list[dict]:
    financial = raw.get("financial_data")
    if isinstance(financial, dict):
        items = financial.get("products") or []
        return [p for p in items if isinstance(p, dict)]
    return []


def _product_lookup(user_id: int) -> dict[str, Product]:
    lookup: dict[str, Product] = {}
    for product in Product.query.filter_by(user_id=user_id).all():
        if product.offer_id:
            lookup[f"offer:{product.offer_id}"] = product
        if product.sku:
            lookup[f"sku:{product.sku}"] = product
        if product.ozon_product_id:
            lookup[f"ozon:{product.ozon_product_id}"] = product
    return lookup


def _catalog_product(
    user_id: int,
    posting_product: dict,
    financial_product: dict | None,
    *,
    product_lookup: dict[str, Product] | None = None,
) -> Product | None:
    offer_id = posting_product.get("offer_id")
    if offer_id:
        if product_lookup is not None:
            found = product_lookup.get(f"offer:{offer_id}")
        else:
            found = Product.query.filter_by(user_id=user_id, offer_id=str(offer_id)).first()
        if found:
            return found
    for src in (posting_product, financial_product or {}):
        for key in ("sku", "product_id"):
            val = src.get(key)
            if not val:
                continue
            text = str(val)
            if product_lookup is not None:
                found = product_lookup.get(f"sku:{text}") or product_lookup.get(f"ozon:{text}")
            else:
                found = Product.query.filter_by(user_id=user_id, sku=text).first()
                if not found:
                    found = Product.query.filter_by(user_id=user_id, ozon_product_id=text).first()
            if found:
                return found
    return None


def _product_rows(
    user_id: int,
    raw: dict,
    fallback_thumb: str | None,
    *,
    product_lookup: dict[str, Product] | None = None,
) -> list[dict]:
    posting_items = _posting_products(raw)
    financial_items = _financial_products(raw)
    rows = []

    if not posting_items and financial_items:
        posting_items = [{"name": "Товар", "offer_id": "", "price": 0, "quantity": 1}]

    for idx, item in enumerate(posting_items):
        fin = financial_items[idx] if idx < len(financial_items) else {}
        catalog = _catalog_product(user_id, item, fin, product_lookup=product_lookup)
        qty = _decimal(fin.get("quantity") or item.get("quantity") or 1)
        price = item.get("price") or fin.get("price") or 0
        customer_price = _decimal(fin.get("customer_price") or 0)
        customer_currency_code = str(
            fin.get("customer_currency_code") or item.get("customer_currency_code") or ""
        ).upper()
        currency_code = str(item.get("currency_code") or fin.get("currency_code") or "RUB").upper()
        if not customer_currency_code:
            customer_currency_code = currency_code
        unit_price_rub = _decimal(fin.get("price") or item.get("price") or 0)
        customer_price_rub = _money(unit_price_rub * qty) if unit_price_rub > 0 else None
        thumb = fallback_thumb
        if catalog and catalog.thumbnail_url:
            thumb = catalog.thumbnail_url
        if not thumb:
            thumb = resolve_thumbnail_url(user_id, {"products": [item], "financial_data": {"products": [fin]}})

        barcode = (catalog.barcode if catalog else None) or "—"
        purchase_unit = (
            float(catalog.purchase_price)
            if catalog and catalog.purchase_price is not None
            else None
        )
        from app.services.order_promotions import promotion_info_for_line

        promo = promotion_info_for_line(raw, item, fin, idx)
        rows.append(
            {
                "thumbnail_url": thumb,
                "name": str(item.get("name") or (catalog.name if catalog else "—")),
                "offer_id": str(item.get("offer_id") or (catalog.offer_id if catalog else "—")),
                "barcode": barcode,
                "quantity": float(qty),
                "price": _money(price),
                "currency_code": currency_code,
                "sale_amount": _money(_decimal(price) * qty),
                "purchase_price": purchase_unit,
                "customer_price": _money(customer_price * qty) if customer_price > 0 else None,
                "customer_currency_code": customer_currency_code,
                "customer_price_rub": customer_price_rub,
                "in_promotion": promo.get("in_promotion"),
                "promotion_titles": promo.get("titles") or [],
            }
        )
    return rows


# Ячейка товара, если в отправлении не удалось определить ни одной позиции.
EMPTY_PRODUCT_CELL = {
    "title": "—",
    "name": "—",
    "quantity": 0,
    "offer_id": "—",
    "barcode": "—",
    "thumbnail_url": None,
    "in_promotion": False,
    "promotion_titles": [],
}


def build_product_cell(row: dict) -> dict:
    """Ячейка одного товара для колонки «Товар» в списках заказов."""
    qty = int(row.get("quantity") or 1)
    name = str(row.get("name") or "—")
    return {
        "title": f"{qty} шт. {name}",
        "name": name,
        "quantity": qty,
        "offer_id": str(row.get("offer_id") or "—"),
        "barcode": str(row.get("barcode") or "—"),
        "thumbnail_url": row.get("thumbnail_url") or None,
        "in_promotion": bool(row.get("in_promotion")),
        "promotion_titles": [
            str(title) for title in (row.get("promotion_titles") or []) if title
        ],
    }


def attach_order_product_cells(orders: list, user_id: int) -> None:
    """Данные для колонки товара в списке заказов (как на странице «Товары»).

    В одном отправлении может быть несколько разных товаров — сохраняем все
    позиции (`order._product_cells`), чтобы список показывал каждую из них.
    """
    if not orders:
        return

    product_lookup = _product_lookup(user_id)
    for order in orders:
        raw = order.raw_data if isinstance(order.raw_data, dict) else {}
        rows = _product_rows(
            user_id,
            raw,
            order.thumbnail_url,
            product_lookup=product_lookup,
        )
        cells = [build_product_cell(row) for row in rows]
        order._product_cells = cells
        order._product_cell = cells[0] if cells else dict(EMPTY_PRODUCT_CELL)


def _apply_product_margins(
    products: list[dict],
    total_accrued: float,
    *,
    is_international: bool = False,
    calculate: bool = True,
) -> list[dict]:
    """Маржа = итого начислено (доля по строке) − закуп (по строке)."""
    if not products:
        return products

    accrued = _decimal(total_accrued)
    sale_amounts = [_decimal(p.get("sale_amount")) for p in products]
    sale_sum = sum(sale_amounts)

    enriched: list[dict] = []
    for product, sale_amount in zip(products, sale_amounts):
        row = dict(product)
        if not calculate:
            row["margin"] = None
            enriched.append(row)
            continue

        if sale_sum > 0 and len(products) > 1:
            accrued_share = accrued * (sale_amount / sale_sum)
        else:
            accrued_share = accrued

        purchase_unit = product.get("purchase_price")
        if purchase_unit is None:
            row["margin"] = None
        else:
            purchase_total = _decimal(purchase_unit) * _decimal(product.get("quantity") or 1)
            if is_international:
                buyout_amount = product.get("buyout_amount")
                if buyout_amount is None:
                    row["margin"] = None
                else:
                    row["margin"] = _money(_decimal(buyout_amount) - purchase_total)
            else:
                row["margin"] = _money(accrued_share - purchase_total)
        enriched.append(row)

    return enriched


def _sum_order_margin(products: list[dict]) -> float | None:
    if not products:
        return None
    margins = [product.get("margin") for product in products]
    if any(margin is None for margin in margins):
        return None
    return _money(sum(margins))


def _cached_total_accrued(raw: dict | None) -> float | None:
    if not isinstance(raw, dict) or not _financial_cache_usable(raw):
        return None
    value = raw.get("_total_accrued")
    if value is None:
        return None
    try:
        return _money(value)
    except (TypeError, ValueError):
        return None


FINANCIAL_RAW_CACHE_KEYS = (
    "_total_accrued",
    "_margin",
    "_accruals",
    "_accruals_version",
    "_accruals_source",
    "_financial_refund",
)
PROMOTION_RAW_CACHE_KEYS = ("_product_promotions",)

# Локальные отметки сервиса, которые не приходят из Ozon и не должны теряться при синхронизации.
LOCAL_RAW_KEYS = (LABEL_DOWNLOADED_RAW_KEY,)

# v3: строки начислений строятся из /v1/finance/accrual/postings.
# v2 хранил неполные строки, полученные из устаревшего /v3/finance/transaction/list,
# поэтому такие кэши перестаём доверять и пересчитываем.
ACCRUALS_CACHE_VERSION = 3

ACCRUALS_SOURCE_API = "accruals"
ACCRUALS_SOURCE_FINANCIAL = "financial"
ACCRUALS_SOURCE_CACHE = "cache"


def _accrual_rows_look_incomplete(rows: list[dict]) -> bool:
    """Кроме выручки нет ни одного начисления — в Ozon данные ещё не полные."""
    if not rows:
        return True
    for row in rows:
        items = row.get("items") if row.get("type") == "group" else [row]
        for item in items or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "")
            if label and label != "Выручка":
                return False
    return True


def _financial_cache_usable(raw: dict | None) -> bool:
    if not isinstance(raw, dict):
        return False
    if raw.get("_accruals_version") != ACCRUALS_CACHE_VERSION:
        return False
    accruals = raw.get("_accruals")
    if not isinstance(accruals, list) or not accruals:
        return False
    return not _accrual_rows_look_incomplete(accruals)


def clear_financial_cache(order) -> None:
    raw = order.raw_data if isinstance(order.raw_data, dict) else {}
    if not isinstance(raw, dict) or not any(key in raw for key in FINANCIAL_RAW_CACHE_KEYS):
        return
    order.raw_data = {k: v for k, v in raw.items() if k not in FINANCIAL_RAW_CACHE_KEYS}


def _cached_accruals(raw: dict | None) -> list[dict] | None:
    if not _financial_cache_usable(raw):
        return None
    return raw.get("_accruals")


def _cached_margin(raw: dict | None) -> float | None:
    if not isinstance(raw, dict):
        return None
    value = raw.get("_margin")
    if value is None:
        return None
    if _cached_buyout_amount(raw) is not None:
        try:
            return _money(value)
        except (TypeError, ValueError):
            return None
    if not _financial_cache_usable(raw):
        return None
    try:
        return _money(value)
    except (TypeError, ValueError):
        return None


def _persist_financial_cache(
    order,
    accruals: list[dict],
    total_accrued: float,
    *,
    source: str,
) -> None:
    """Кэшируем только строки из API начислений: данные из financial_data неполные."""
    if source != ACCRUALS_SOURCE_API or _accrual_rows_look_incomplete(accruals):
        return
    _persist_total_accrued_cache(order, total_accrued)
    _persist_accruals_cache(order, accruals)
    persist_financial_refund_cache(
        order,
        detect_financial_refund(accruals=accruals, total_accrued=total_accrued),
    )


def _persist_total_accrued_cache(order, total_accrued: float) -> None:
    raw = order.raw_data if isinstance(order.raw_data, dict) else {}
    cached = _cached_total_accrued(raw)
    total = _money(total_accrued)
    if cached == total:
        return
    order.raw_data = {**raw, "_total_accrued": total}


def merge_order_raw_data(
    old_raw: dict | None,
    new_raw: dict | None,
    *,
    old_status: str,
    new_status: str,
) -> dict:
    """Сохраняет кэш начислений/маржи при быстрой синхронизации списка заказов."""
    merged = dict(new_raw) if isinstance(new_raw, dict) else {}
    if not isinstance(old_raw, dict):
        return merged
    if old_status == ORDER_STATUS_DELIVERED and new_status == ORDER_STATUS_DELIVERED:
        for key in (*FINANCIAL_RAW_CACHE_KEYS, *BUYOUT_RAW_CACHE_KEYS):
            if key in old_raw:
                merged[key] = old_raw[key]
    for key in PROMOTION_RAW_CACHE_KEYS:
        if key in old_raw:
            merged[key] = old_raw[key]
    for key in LOCAL_RAW_KEYS:
        if key in old_raw:
            merged[key] = old_raw[key]
    return merged


def _persist_accruals_cache(order, accruals: list[dict]) -> None:
    if _accrual_rows_look_incomplete(accruals):
        return
    raw = order.raw_data if isinstance(order.raw_data, dict) else {}
    current = _cached_accruals(raw)
    if current == accruals:
        return
    order.raw_data = {
        **raw,
        "_accruals": accruals,
        "_accruals_version": ACCRUALS_CACHE_VERSION,
        "_accruals_source": ACCRUALS_SOURCE_API,
    }


def _persist_margin_cache(order, margin: float | None) -> None:
    raw = order.raw_data if isinstance(order.raw_data, dict) else {}
    current = _cached_margin(raw)
    if margin is None:
        if "_margin" in raw:
            new_raw = dict(raw)
            new_raw.pop("_margin", None)
            order.raw_data = new_raw
        return
    normalized = _money(margin)
    if current == normalized:
        return
    order.raw_data = {**raw, "_margin": normalized}


def resolve_total_accrued(
    order,
    raw: dict,
    *,
    user=None,
    use_transactions: bool = True,
    accruals_lookup: PostingAccruals | None = None,
) -> float:
    """Итого начислено: из кэша в raw_data или из API начислений (как в модалке)."""
    cached = _cached_total_accrued(raw)
    if cached is not None:
        if use_transactions and _cached_accruals(raw) is None:
            user = user or order.user
            if user and user.has_ozon_credentials():
                accruals, total_accrued, source = _accrual_rows(
                    raw,
                    _decimal(order.total),
                    user=user,
                    posting_number=order.ozon_order_id,
                    use_transactions=True,
                    accruals_lookup=accruals_lookup,
                )
                _persist_financial_cache(order, accruals, total_accrued, source=source)
                if total_accrued != cached:
                    return total_accrued
        return cached

    user = user or order.user
    accruals, total_accrued, source = _accrual_rows(
        raw,
        _decimal(order.total),
        user=user,
        posting_number=order.ozon_order_id,
        use_transactions=use_transactions,
        accruals_lookup=accruals_lookup,
    )
    if use_transactions and user and user.has_ozon_credentials():
        _persist_financial_cache(order, accruals, total_accrued, source=source)
    return total_accrued


def compute_order_margin(
    order,
    *,
    user=None,
    use_transactions: bool = True,
    product_lookup: dict[str, Product] | None = None,
    buyout_index: dict[str, list[dict]] | None = None,
    accruals_lookup: PostingAccruals | None = None,
) -> float | None:
    if order.status != ORDER_STATUS_DELIVERED:
        return None

    from app.services.order_returns import order_has_refund_after_delivery

    if order_has_refund_after_delivery(order):
        return None

    raw = order.raw_data if isinstance(order.raw_data, dict) else {}
    cached_margin = _cached_margin(raw)
    if cached_margin is not None and not use_transactions:
        return cached_margin

    products = _product_rows(
        order.user_id,
        raw,
        order.thumbnail_url,
        product_lookup=product_lookup,
    )
    is_international = order.is_international()
    if is_international:
        apply_buyout_to_products(
            order,
            products,
            user=user,
            use_api=use_transactions,
            buyout_index=buyout_index,
        )
        total_accrued = _cached_buyout_amount(
            order.raw_data if isinstance(order.raw_data, dict) else {}
        ) or 0.0
    else:
        total_accrued = resolve_total_accrued(
            order,
            raw,
            user=user,
            use_transactions=use_transactions,
            accruals_lookup=accruals_lookup,
        )
    products = _apply_product_margins(
        products,
        total_accrued,
        is_international=is_international,
        calculate=True,
    )
    margin = _sum_order_margin(products)
    if is_international:
        if _cached_buyout_amount(order.raw_data if isinstance(order.raw_data, dict) else {}) is not None:
            _persist_margin_cache(order, margin)
    elif use_transactions and _financial_cache_usable(
        order.raw_data if isinstance(order.raw_data, dict) else {}
    ):
        _persist_margin_cache(order, margin)
    return margin


def load_batch_accruals(user, orders: list) -> PostingAccruals | None:
    """Начисления Ozon на пачку доставленных заказов: до 200 отправлений в одном запросе."""
    if not user or not user.has_ozon_credentials():
        return None

    posting_numbers = [
        order.ozon_order_id
        for order in orders
        if order.status == ORDER_STATUS_DELIVERED
        and order.ozon_order_id
        and not order.is_international()
    ]
    if not posting_numbers:
        return None
    return load_posting_accruals(
        user.ozon_client_id,
        user.ozon_api_key,
        posting_numbers,
    )


def attach_order_margins(
    orders: list,
    user,
    *,
    use_transactions: bool = False,
    accruals_lookup: PostingAccruals | None = None,
) -> None:
    """Маржа для списка: из кэша в raw_data, без внешних API при просмотре."""
    if not orders:
        return

    product_lookup = _product_lookup(user.id) if use_transactions else None
    buyout_index = None
    if use_transactions and user.has_ozon_credentials():
        buyout_index = build_buyout_index_for_orders(user, orders)
    pending_commit = False

    with db.session.no_autoflush:
        for order in orders:
            if order.status != ORDER_STATUS_DELIVERED:
                order._list_margin = None
                continue

            from app.services.order_returns import order_has_refund_after_delivery

            if order_has_refund_after_delivery(order):
                order._list_margin = None
                continue

            raw = order.raw_data if isinstance(order.raw_data, dict) else {}
            cached_margin = _cached_margin(raw)
            if cached_margin is not None and not use_transactions:
                order._list_margin = cached_margin
                continue

            cached_before = _cached_total_accrued(raw)
            cached_margin_before = _cached_margin(raw)
            order._list_margin = compute_order_margin(
                order,
                user=user,
                use_transactions=use_transactions,
                product_lookup=product_lookup,
                buyout_index=buyout_index,
                accruals_lookup=accruals_lookup,
            )
            raw_after = order.raw_data if isinstance(order.raw_data, dict) else {}
            cached_after = _cached_total_accrued(raw_after)
            cached_margin_after = _cached_margin(raw_after)
            if cached_before != cached_after or cached_margin_before != cached_margin_after:
                pending_commit = True

    if not pending_commit:
        return

    try:
        db_session_commit()
    except Exception:
        db.session.rollback()


def _seller_price_revenue(accruals: list[dict]) -> Decimal | None:
    """Выручка по начислениям Ozon: сумма seller_price × quantity.

    Стоимость продажи Ozon прикладывает к начислению «Вознаграждение за продажу»,
    а при возврате отдаёт её с отрицательным seller_price — сумма сходится в ноль.
    None означает, что стоимость продажи в ответе отсутствует.
    """
    total: Decimal | None = None
    for accrual in accruals:
        price = accrual.get("seller_price")
        if not isinstance(price, dict):
            continue
        quantity = _decimal(accrual.get("quantity") or 1)
        total = (total or Decimal(0)) + _decimal(price.get("amount")) * quantity
    return total


def _financial_revenue(raw: dict) -> Decimal:
    total = Decimal(0)
    for fin in _financial_products(raw):
        total += _decimal(fin.get("price") or 0) * _decimal(fin.get("quantity") or 1)
    return total


def _accrual_rows_from_accruals(
    raw: dict,
    accruals: list[dict],
    bundle: PostingAccruals,
) -> tuple[list[dict], float]:
    """Строки начислений как в кабинете Ozon: выручка и начисления по типам."""
    seller_revenue = _seller_price_revenue(accruals)
    revenue = seller_revenue if seller_revenue is not None else _financial_revenue(raw)

    grouped: dict[tuple, Decimal] = {}
    order: list[tuple] = []
    dates: list[str] = []
    revenue_dates: list[str] = []
    reversal_keys: set[tuple] = set()
    for accrual in accruals:
        date = str(accrual.get("accrual_date") or "")
        if date:
            dates.append(date)
            if isinstance(accrual.get("seller_price"), dict):
                revenue_dates.append(date)
        key = (accrual.get("type_id"), date)
        if key not in grouped:
            grouped[key] = Decimal(0)
            order.append(key)
        grouped[key] += accrual_amount(accrual)
        seller_price = accrual.get("seller_price")
        if isinstance(seller_price, dict) and _decimal(seller_price.get("amount")) < 0:
            # Сторно продажи: Ozon отдаёт стоимость возврата с минусом.
            reversal_keys.add(key)

    rows: list[dict] = []
    if revenue != 0:
        rows.append(
            {
                "type": "row",
                "label": "Выручка",
                "date": _parse_operation_date(
                    min(revenue_dates) if revenue_dates else (min(dates) if dates else "")
                ),
                "amount": _money(abs(revenue)),
                "negative": revenue < 0,
            }
        )

    accruals_total = Decimal(0)
    for key in order:
        amount = grouped[key]
        accruals_total += amount
        if amount == 0:
            continue
        row = {
            "type": "row",
            "label": bundle.label(key[0]),
            "date": _parse_operation_date(key[1]),
            "amount": _money(abs(amount)),
            "negative": amount < 0,
        }
        if key in reversal_keys:
            row["reversal"] = True
        rows.append(row)

    return rows, _money(revenue + accruals_total)


def _accrual_rows_fallback(raw: dict, order_total: Decimal) -> tuple[list[dict], float]:
    financial_items = _financial_products(raw)
    detail = []
    total = Decimal(0)

    for fin in financial_items:
        qty = _decimal(fin.get("quantity") or 1)
        price = _decimal(fin.get("price") or 0)
        commission = _decimal(fin.get("commission_amount") or 0)
        payout = _decimal(fin.get("payout") or 0)

        if price > 0:
            detail.append({"label": "Выручка", "amount": _money(price * qty), "negative": False})
        if commission != 0:
            detail.append(
                {
                    "label": "Вознаграждение Ozon",
                    "amount": _money(abs(commission) * qty),
                    "negative": commission < 0,
                }
            )
        if payout != 0:
            total = payout * qty

    rows = []
    if detail:
        group_amount = total if total != 0 else sum(
            _decimal(i["amount"]) if not i.get("negative") else -_decimal(i["amount"])
            for i in detail
        )
        rows.append(
            {
                "type": "group",
                "label": "Комиссии Ozon",
                "date": "—",
                "amount": _money(group_amount),
                "negative": group_amount < 0,
                "expanded": True,
                "items": detail,
            }
        )
        return rows, _money(group_amount)

    return [], _money(order_total)


def _accrual_rows(
    raw: dict,
    order_total: Decimal,
    *,
    user,
    posting_number: str,
    use_transactions: bool = True,
    accruals_lookup: PostingAccruals | None = None,
) -> tuple[list[dict], float, str]:
    """Строки начислений, итог и источник: API начислений, кэш или financial_data."""
    if not use_transactions:
        cached_accruals = _cached_accruals(raw)
        cached_total = _cached_total_accrued(raw)
        if cached_accruals is not None and cached_total is not None:
            return cached_accruals, cached_total, ACCRUALS_SOURCE_CACHE
        rows, total = _accrual_rows_fallback(raw, order_total)
        return rows, total, ACCRUALS_SOURCE_FINANCIAL

    if user and user.has_ozon_credentials() and posting_number:
        bundle = accruals_lookup
        if bundle is None:
            bundle = load_posting_accruals(
                user.ozon_client_id,
                user.ozon_api_key,
                [posting_number],
            )
        accruals = bundle.accruals(posting_number)
        if accruals:
            rows, total = _accrual_rows_from_accruals(raw, accruals, bundle)
            return rows, total, ACCRUALS_SOURCE_API

    rows, total = _accrual_rows_fallback(raw, order_total)
    return rows, total, ACCRUALS_SOURCE_FINANCIAL


def _cluster_info(raw: dict) -> dict:
    financial = raw.get("financial_data")
    if not isinstance(financial, dict):
        return {}
    info = {}
    if financial.get("cluster_from"):
        info["cluster_from"] = str(financial["cluster_from"])
    if financial.get("cluster_to"):
        info["cluster_to"] = str(financial["cluster_to"])
    return info


def build_order_detail(
    order,
    raw: dict | None = None,
    *,
    user=None,
    use_live_financials: bool = True,
    accruals_lookup: PostingAccruals | None = None,
) -> dict:
    raw = raw if isinstance(raw, dict) else (order.raw_data if isinstance(order.raw_data, dict) else {})
    order_date = format_datetime(order.order_date)
    user = user or order.user
    is_international = order.is_international()
    use_transactions = use_live_financials
    if (
        not is_international
        and not use_live_financials
        and _cached_accruals(raw) is None
        and user
        and user.has_ozon_credentials()
    ):
        use_transactions = True
    has_return = order_has_refund_after_delivery(order)
    calculate_margin = order.status == ORDER_STATUS_DELIVERED and not has_return
    products = _product_rows(order.user_id, raw, order.thumbnail_url)

    if is_international:
        buyout_total = apply_buyout_to_products(
            order,
            products,
            user=user,
            use_api=use_live_financials,
        )
        total_accrued = buyout_total
        accruals = (
            [
                {
                    "type": "row",
                    "label": "Выкуп маркетплейса",
                    "date": "—",
                    "amount": buyout_total,
                    "negative": False,
                }
            ]
            if buyout_total
            else []
        )
        products = _apply_product_margins(
            products,
            total_accrued,
            is_international=True,
            calculate=calculate_margin,
        )
        if use_live_financials and buyout_total:
            _persist_margin_cache(order, _sum_order_margin(products) if calculate_margin else None)
    else:
        accruals, total_accrued, accruals_source = _accrual_rows(
            raw,
            _decimal(order.total),
            user=user,
            posting_number=order.ozon_order_id,
            use_transactions=use_transactions,
            accruals_lookup=accruals_lookup,
        )
        if not use_transactions:
            cached_accrued = _cached_total_accrued(raw)
            if cached_accrued is not None:
                total_accrued = cached_accrued
        elif user and user.has_ozon_credentials():
            _persist_financial_cache(
                order,
                accruals,
                total_accrued,
                source=accruals_source,
            )
        products = _apply_product_margins(
            products,
            total_accrued,
            is_international=False,
            calculate=calculate_margin,
        )
        if (
            use_live_financials
            and user
            and user.has_ozon_credentials()
            and _financial_cache_usable(order.raw_data if isinstance(order.raw_data, dict) else {})
        ):
            _persist_margin_cache(order, _sum_order_margin(products) if calculate_margin else None)

    return {
        "ok": True,
        "header": {
            "posting_number": order.ozon_order_id,
            "order_date": order_date,
            "scheme": order.scheme_display(),
            "scheme_class": order.scheme.lower(),
            "status": ORDER_STATUS_LABELS.get(order.status, order.status),
            "is_international": order.is_international(),
            "delivery_country": order.delivery_country(),
            "customer_currency": order.customer_currency(),
            "margin_currency": "RUB",
            "has_post_delivery_return": has_return,
            "has_financial_refund": order_has_financial_refund(order),
            "refund_tooltip": refund_after_delivery_tooltip(order),
        },
        "products": products,
        "clusters": _cluster_info(raw),
        "accruals": accruals,
        "total_accrued": total_accrued,
    }


def get_order_detail(user, order_id: int, *, refresh: bool = False) -> dict:
    from app.models import Order

    order = Order.query.filter_by(id=order_id, user_id=user.id).first()
    if not order:
        return {"ok": False, "error": "Заказ не найден."}

    raw = order.raw_data if isinstance(order.raw_data, dict) else {}
    if refresh and user.has_ozon_credentials():
        fresh = fetch_posting_detail(user, order.ozon_order_id, order.scheme)
        if fresh:
            old_raw = order.raw_data if isinstance(order.raw_data, dict) else {}
            cached_accrued = _cached_total_accrued(old_raw)
            cached_margin = _cached_margin(old_raw)
            raw = fresh
            if cached_accrued is not None:
                raw["_total_accrued"] = cached_accrued
            if cached_margin is not None:
                raw["_margin"] = cached_margin
            for key in BUYOUT_RAW_CACHE_KEYS:
                if key in old_raw:
                    raw[key] = old_raw[key]
            for key in PROMOTION_RAW_CACHE_KEYS:
                if key in old_raw:
                    raw[key] = old_raw[key]
            order.raw_data = raw
            from app.services.order_promotions import apply_product_promotions, fetch_known_promotion_titles

            known_titles: set[str] = set()
            if user.has_ozon_credentials():
                try:
                    known_titles = fetch_known_promotion_titles(
                        user.ozon_client_id,
                        user.ozon_api_key,
                    )
                except Exception:
                    known_titles = set()
            apply_product_promotions(
                order,
                user_id=user.id,
                known_titles=known_titles,
                force_refresh=True,
            )
            db_session_commit()

    had_accruals_cache = _cached_accruals(order.raw_data if isinstance(order.raw_data, dict) else None) is not None
    detail = build_order_detail(
        order,
        raw,
        user=user,
        use_live_financials=refresh,
    )
    if refresh or (not refresh and not had_accruals_cache and _cached_accruals(order.raw_data) is not None):
        try:
            db_session_commit()
        except Exception:
            db.session.rollback()
    return detail
