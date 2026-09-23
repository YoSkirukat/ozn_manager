"""Остатки FBS из внешнего Excel + выгрузка в Ozon по FBS-складам."""

from __future__ import annotations

import io
import re

import requests
from sqlalchemy import func

from app.datetime_fmt import format_datetime, to_iso_utc
from app.db_sqlite import db_session_commit
from app.extensions import db
from app.models import FbsStockSource, Product, ProductFbsStock, utcnow
from app.ozon.fbs_stocks import resolve_fbs_warehouse_id, update_fbs_stocks
from app.services.purchase_prices import normalize_barcode, normalize_sheet_url

CHUNK_SIZE = 400

BARCODE_HEADERS = {"баркод", "barcode", "штрихкод", "штрих-код"}
STOCK_HEADERS = {
    "остаток fbs",
    "остатки fbs",
    "остаток",
    "остатки",
    "количество",
    "кол-во",
    "stock",
    "stock_fbs",
    "fbs",
}


def _normalize_header(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _parse_stock(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        if value != value:
            return None
        return max(0, int(value))
    text = str(value).strip().replace(" ", "").replace(",", ".")
    text = re.sub(r"[^\d.\-]", "", text)
    if not text:
        return None
    try:
        return max(0, int(float(text)))
    except (TypeError, ValueError):
        return None


def _find_columns(headers: list) -> tuple[int | None, int | None]:
    barcode_col = None
    stock_col = None
    for idx, header in enumerate(headers):
        norm = _normalize_header(header)
        if norm in BARCODE_HEADERS:
            barcode_col = idx
        if norm in STOCK_HEADERS or norm.startswith("остаток"):
            stock_col = idx
    return barcode_col, stock_col


def _parse_workbook(content: bytes) -> dict[str, int]:
    if content[:2] == b"PK":
        return _parse_xlsx(content)
    return _parse_xls(content)


def _parse_xlsx(content: bytes) -> dict[str, int]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    return _rows_to_stocks(rows)


def _parse_xls(content: bytes) -> dict[str, int]:
    import xlrd

    book = xlrd.open_workbook(file_contents=content)
    sheet = book.sheet_by_index(0)
    rows = [sheet.row_values(r) for r in range(sheet.nrows)]
    return _rows_to_stocks(rows)


def _rows_to_stocks(rows: list) -> dict[str, int]:
    if not rows:
        raise ValueError("Файл пуст.")

    header_row = None
    header_index = 0
    for i, row in enumerate(rows[:20]):
        if not row:
            continue
        bc, st = _find_columns(list(row))
        if bc is not None and st is not None:
            header_row = list(row)
            header_index = i
            break

    if header_row is None:
        raise ValueError('Не найдены колонки «Баркод» и «Остаток FBS».')

    barcode_col, stock_col = _find_columns(header_row)
    stocks: dict[str, int] = {}

    for row in rows[header_index + 1 :]:
        if not row or len(row) <= max(barcode_col, stock_col):
            continue
        barcode = normalize_barcode(row[barcode_col])
        stock = _parse_stock(row[stock_col])
        if barcode and stock is not None:
            stocks[barcode] = stock

    if not stocks:
        raise ValueError("В файле нет строк с баркодом и остатком.")
    return stocks


def fetch_fbs_stocks_map(url: str) -> dict[str, int]:
    download_url = normalize_sheet_url(url)
    try:
        resp = requests.get(download_url, timeout=60)
    except requests.RequestException as exc:
        raise RuntimeError(f"Не удалось скачать файл: {exc}") from exc
    if resp.status_code != 200:
        raise RuntimeError(f"Ошибка загрузки файла: HTTP {resp.status_code}")
    return _parse_workbook(resp.content)


def list_fbs_stock_sources(user_id: int) -> list[FbsStockSource]:
    """Настройки складов FBS пользователя: склад Ozon + ссылка на файл остатков."""
    return (
        FbsStockSource.query.filter_by(user_id=user_id)
        .order_by(FbsStockSource.id.asc())
        .all()
    )


def fbs_source_label(source: dict) -> str:
    name = (source.get("warehouse_name") or "").strip()
    warehouse_id = str(source.get("warehouse_id") or "").strip()
    if not warehouse_id:
        return name or "Автовыбор FBS-склада"
    if name:
        return f"{name} ({warehouse_id})"
    return f"Склад {warehouse_id}"


def _legacy_fbs_source(user) -> dict | None:
    """Одиночная настройка из профиля (до разделения остатков по складам)."""
    url = (getattr(user, "fbs_stocks_url", None) or "").strip()
    if not url:
        return None
    return {
        "warehouse_id": (getattr(user, "fbs_warehouse_id", None) or "").strip(),
        "warehouse_name": None,
        "stocks_url": url,
        "legacy": True,
    }


def collect_fbs_sources(user) -> list[dict]:
    """Источники остатков: настроенные по складам либо устаревшая одиночная настройка."""
    sources = [
        {
            "warehouse_id": str(source.warehouse_id or ""),
            "warehouse_name": source.warehouse_name,
            "stocks_url": (source.stocks_url or "").strip(),
            "legacy": False,
        }
        for source in list_fbs_stock_sources(user.id)
    ]
    sources = [source for source in sources if source["stocks_url"]]
    if sources:
        return sources
    legacy = _legacy_fbs_source(user)
    return [legacy] if legacy else []


def _source_warehouse_id(source: dict) -> int | None:
    raw = str(source.get("warehouse_id") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _chunks(values: list, size: int = CHUNK_SIZE):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _warehouse_stock_records(user_id: int, warehouse_id: str) -> dict[int, ProductFbsStock]:
    rows = ProductFbsStock.query.filter_by(
        user_id=user_id,
        warehouse_id=warehouse_id,
    ).all()
    return {int(row.product_id): row for row in rows}


def _recalculate_product_totals(user_id: int, product_ids: list[int]) -> int:
    """Суммарный остаток FBS товара = сумма остатков по всем его складам."""
    unique_ids = list({int(pid) for pid in product_ids})
    if not unique_ids:
        return 0

    totals: dict[int, int] = {}
    for chunk in _chunks(unique_ids):
        rows = (
            db.session.query(
                ProductFbsStock.product_id,
                func.coalesce(func.sum(ProductFbsStock.stock), 0),
            )
            .filter(
                ProductFbsStock.user_id == user_id,
                ProductFbsStock.product_id.in_(chunk),
            )
            .group_by(ProductFbsStock.product_id)
            .all()
        )
        for product_id, total in rows:
            totals[int(product_id)] = int(total or 0)

    changed = 0
    for chunk in _chunks(unique_ids):
        products = Product.query.filter(
            Product.user_id == user_id,
            Product.id.in_(chunk),
        ).all()
        for product in products:
            total = totals.get(int(product.id), 0)
            if int(product.stock_fbs or 0) != total:
                changed += 1
            product.stock_fbs = total
    return changed


def _delete_product_stocks(user_id: int, warehouse_ids: set[str]) -> None:
    if not warehouse_ids:
        return
    ProductFbsStock.query.filter(
        ProductFbsStock.user_id == user_id,
        ProductFbsStock.warehouse_id.in_(list(warehouse_ids)),
    ).delete(synchronize_session=False)


def save_fbs_stock_sources(user, rows: list[dict]) -> dict:
    """Полностью заменяет настройки остатков FBS (склад + ссылка на файл)."""
    normalized: list[dict] = []
    seen: set[str] = set()
    skipped_without_url = 0
    duplicates = 0

    for row in rows:
        warehouse_id = str(row.get("warehouse_id") or "").strip()
        if warehouse_id.lower() in {"auto", "__auto__"}:
            warehouse_id = FbsStockSource.AUTO_WAREHOUSE_ID
        if warehouse_id and not warehouse_id.isdigit():
            return {"ok": False, "error": f"Некорректный ID склада FBS: {warehouse_id}."}

        stocks_url = str(row.get("stocks_url") or "").strip()
        if not stocks_url:
            skipped_without_url += 1
            continue
        if warehouse_id in seen:
            duplicates += 1
            continue

        seen.add(warehouse_id)
        normalized.append(
            {
                "warehouse_id": warehouse_id,
                "warehouse_name": (row.get("warehouse_name") or "").strip() or None,
                "stocks_url": stocks_url,
            }
        )

    existing = {
        str(source.warehouse_id or ""): source
        for source in list_fbs_stock_sources(user.id)
    }

    for item in normalized:
        source = existing.pop(item["warehouse_id"], None)
        if source is None:
            source = FbsStockSource(user_id=user.id, warehouse_id=item["warehouse_id"])
            db.session.add(source)
        source.warehouse_name = item["warehouse_name"]
        source.stocks_url = item["stocks_url"]

    removed_ids = set(existing.keys())
    if removed_ids:
        affected = [
            int(product_id)
            for (product_id,) in db.session.query(ProductFbsStock.product_id)
            .filter(
                ProductFbsStock.user_id == user.id,
                ProductFbsStock.warehouse_id.in_(list(removed_ids)),
            )
            .all()
        ]
        for source in existing.values():
            db.session.delete(source)
        _delete_product_stocks(user.id, removed_ids)
        _recalculate_product_totals(user.id, affected)

    return {
        "ok": True,
        "saved": len(normalized),
        "removed": len(removed_ids),
        "skipped_without_url": skipped_without_url,
        "duplicates": duplicates,
    }


def _build_ozon_items(
    user,
    stock_map: dict[str, int],
    warehouse_records: dict[int, ProductFbsStock],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Позиции по файлу склада.

    Возвращает (изменившиеся для Ozon, все совпадения по баркоду, товары в архиве Ozon).
    """
    products = Product.query.filter_by(user_id=user.id).all()
    matched: list[dict] = []
    changed: list[dict] = []
    archived: list[dict] = []

    for product in products:
        barcode = normalize_barcode(product.barcode)
        if not barcode:
            continue
        stock = stock_map.get(barcode)
        if stock is None:
            continue

        record = warehouse_records.get(int(product.id))
        current_stock = int(record.stock) if record is not None else 0
        entry: dict = {
            "stock": stock,
            "current_stock": current_stock,
            "product": product,
        }
        if product.ozon_product_id:
            entry["product_id"] = product.ozon_product_id
        if product.offer_id:
            entry["offer_id"] = product.offer_id
        matched.append(entry)

        if current_stock == stock:
            continue
        if product.is_archived_in_ozon():
            # Ozon не принимает положительные остатки по архиву — даже не отправляем.
            archived.append(entry)
            continue
        if "product_id" not in entry and "offer_id" not in entry:
            continue
        changed.append(entry)

    return changed, matched, archived


def _store_warehouse_stocks(
    user_id: int,
    warehouse_id: str,
    matched_items: list[dict],
    *,
    skipped_product_ids: set[int] | None = None,
) -> int:
    """Сохраняет остатки товаров по складу (кроме позиций, отклонённых Ozon)."""
    skipped = skipped_product_ids or set()
    records = _warehouse_stock_records(user_id, warehouse_id)
    now = utcnow()
    updated = 0

    for item in matched_items:
        product = item.get("product")
        if product is None:
            continue
        product_id = int(product.id)
        if product_id in skipped:
            continue

        stock = int(item["stock"])
        record = records.get(product_id)
        if record is None:
            record = ProductFbsStock(
                user_id=user_id,
                product_id=product_id,
                warehouse_id=warehouse_id,
            )
            db.session.add(record)
            records[product_id] = record
        if int(record.stock or 0) != stock:
            updated += 1
        record.stock = stock
        record.updated_at = now

    return updated


def product_fbs_stock_breakdown(user, product) -> dict:
    """Остатки товара по FBS-складам (модалка на странице «Товары»)."""
    sources = list_fbs_stock_sources(user.id)
    records = {
        str(row.warehouse_id or ""): row
        for row in ProductFbsStock.query.filter_by(
            user_id=user.id,
            product_id=product.id,
        ).all()
    }

    warehouses: list[dict] = []
    known: set[str] = set()

    def append_row(warehouse_id: str, name: str | None, label: str, record) -> None:
        warehouses.append(
            {
                "warehouse_id": warehouse_id,
                "warehouse_name": name,
                "label": label,
                "stock": int(record.stock) if record is not None else None,
                "has_data": record is not None,
                "updated_at": to_iso_utc(record.updated_at) if record is not None else None,
                "updated_at_display": (
                    format_datetime(record.updated_at) if record is not None else None
                ),
            }
        )

    for source in sources:
        warehouse_id = str(source.warehouse_id or "")
        known.add(warehouse_id)
        append_row(
            warehouse_id,
            source.warehouse_name,
            source.warehouse_label(),
            records.get(warehouse_id),
        )

    for warehouse_id, record in records.items():
        if warehouse_id in known:
            continue
        label = f"Склад {warehouse_id}" if warehouse_id else "Автовыбор FBS-склада"
        append_row(warehouse_id, None, label, record)

    has_any_data = any(item["has_data"] for item in warehouses)
    total = (
        sum(int(item["stock"] or 0) for item in warehouses if item["has_data"])
        if has_any_data
        else int(product.stock_fbs or 0)
    )

    return {
        "product": {
            "id": product.id,
            "name": product.name,
            "offer_id": product.offer_id or "—",
            "barcode": product.barcode or "—",
            "thumbnail_url": product.thumbnail_url,
            "total": total,
        },
        "warehouses": warehouses,
    }


def _item_lookup_key(item: dict) -> str:
    if item.get("offer_id") not in (None, ""):
        return f"offer:{item['offer_id']}"
    if item.get("product_id") not in (None, ""):
        return f"product:{item['product_id']}"
    return ""


def _resolve_source_item(by_key: dict, raw: dict) -> dict | None:
    """Находит исходную позицию по элементу ответа Ozon (там нет объекта product)."""
    item = by_key.get(_item_lookup_key(raw))
    if item is None and raw.get("product_id") not in (None, ""):
        item = by_key.get(f"product:{raw['product_id']}")
    return item


def _index_items_by_keys(items: list[dict]) -> dict[str, dict]:
    by_key: dict[str, dict] = {}
    for item in items:
        if item.get("offer_id") not in (None, ""):
            by_key[f"offer:{item['offer_id']}"] = item
        product_id = item.get("product_id")
        if product_id not in (None, ""):
            by_key[f"product:{product_id}"] = item
            try:
                by_key[f"product:{int(product_id)}"] = item
            except (TypeError, ValueError):
                pass
    return by_key


def _apply_stock_map(
    user,
    stock_map: dict[str, int],
    *,
    push_to_ozon: bool = True,
    source: dict | None = None,
) -> dict:
    source = source or {"warehouse_id": "", "warehouse_name": None, "stocks_url": ""}
    warehouse_key = str(source.get("warehouse_id") or "")
    label = fbs_source_label(source)

    warehouse_records = _warehouse_stock_records(user.id, warehouse_key)
    changed_items, matched_items, archived_local_items = _build_ozon_items(
        user, stock_map, warehouse_records
    )

    result = {
        "ok": True,
        "skipped": False,
        "updated": 0,
        "warehouse_id": warehouse_key,
        "warehouse_name": source.get("warehouse_name"),
        "total_in_file": len(stock_map),
        "matched": len(matched_items),
        "changed": len(changed_items),
        "archived": 0,
        "ozon_updated": 0,
        "ozon_failed": 0,
        "ozon_deferred": 0,
    }

    if not matched_items:
        result["message"] = (
            f"{label}: в файле {len(stock_map)} строк, но нет совпадений с товарами "
            "в каталоге (по баркоду)."
        )
        return result

    skipped_product_ids: set[int] = set()
    # Товары в архиве Ozon: остатки по ним не выгружаются и в приложении не меняются.
    archived_products: dict[int, str] = {}
    for item in archived_local_items:
        product = item.get("product")
        if product is not None:
            archived_products[int(product.id)] = product.ozon_offer_label()

    if push_to_ozon:
        if not user.has_ozon_credentials():
            result["ok"] = False
            result["error"] = "Подключите Ozon API в профиле, чтобы выгрузить остатки в кабинет."
            result["message"] = f"{label}: в Ozon не отправлено — нет ключей API."
            return result

        if changed_items:
            by_key = _index_items_by_keys(changed_items)
            ozon_payload = [
                {k: v for k, v in item.items() if k not in ("product", "current_stock")}
                for item in changed_items
            ]

            try:
                ozon_warehouse_id = resolve_fbs_warehouse_id(
                    user.ozon_client_id,
                    user.ozon_api_key,
                    _source_warehouse_id(source),
                )
                ozon_result = update_fbs_stocks(
                    user.ozon_client_id,
                    user.ozon_api_key,
                    ozon_warehouse_id,
                    ozon_payload,
                )
            except Exception as exc:
                result["ok"] = False
                result["error"] = f"{label}: {exc}"
                result["message"] = f"{label}: ошибка выгрузки в Ozon — {exc}"
                return result

            result["warehouse_id"] = str(ozon_warehouse_id)
            result["ozon_updated"] = int(ozon_result.get("updated") or 0)
            result["ozon_failed"] = int(ozon_result.get("failed") or 0)
            result["ozon_deferred"] = int(ozon_result.get("deferred") or 0)

            accepted_ids: set[int] = set()
            for raw in ozon_result.get("updated_items") or []:
                src_item = _resolve_source_item(by_key, raw)
                if src_item is not None:
                    accepted_ids.add(int(src_item["product"].id))

            skipped_product_ids = {
                int(item["product"].id)
                for item in changed_items
                if int(item["product"].id) not in accepted_ids
            }

            # Ozon отказал по причине архива: помечаем товары, чтобы не повторять выгрузку.
            for raw in ozon_result.get("archived_items") or []:
                src_item = _resolve_source_item(by_key, raw)
                if src_item is None:
                    continue
                product = src_item["product"]
                product_id = int(product.id)
                product.mark_fbs_archived_stock_skip()
                archived_products[product_id] = product.ozon_offer_label()
                skipped_product_ids.add(product_id)

            if not ozon_result.get("ok"):
                result["ok"] = False
                errors = ozon_result.get("errors") or []
                err_tail = " " + "; ".join(errors[:5]) if errors else ""
                result["error"] = (
                    f"{label}: часть остатков не обновлена в Ozon "
                    f"(успешно {result['ozon_updated']}, ошибок {result['ozon_failed']}).{err_tail}"
                )

    result["archived"] = len(archived_products)
    if archived_products:
        result["archived_items"] = [
            {"product_id": product_id, "label": item_label}
            for product_id, item_label in list(archived_products.items())[:20]
        ]

    skipped_product_ids |= set(archived_products.keys())
    _store_warehouse_stocks(
        user.id,
        warehouse_key,
        matched_items,
        skipped_product_ids=skipped_product_ids,
    )
    local_updated = _recalculate_product_totals(
        user.id,
        [
            int(item["product"].id)
            for item in matched_items
            if int(item["product"].id) not in skipped_product_ids
        ],
    )
    result["updated"] = local_updated

    if not result["ok"]:
        result["message"] = result.get("error") or f"{label}: не удалось обновить остатки."
        return result

    parts = [f"{label}: в файле {len(stock_map)}, совпадений {len(matched_items)}"]
    if push_to_ozon:
        if changed_items:
            parts.append(f"в Ozon отправлено {result['ozon_updated']}")
            if result["ozon_deferred"]:
                parts.append(f"отложено из-за частоты {result['ozon_deferred']}")
        elif archived_products:
            parts.append("изменения только по товарам в архиве Ozon — в Ozon не отправляли")
        else:
            parts.append("изменений остатков нет — в Ozon не отправляли")
    if archived_products:
        labels = list(archived_products.values())
        shown = ", ".join(labels[:2])
        if len(labels) > 2:
            shown += f" и ещё {len(labels) - 2}"
        parts.append(f"пропущено товаров в архиве Ozon: {len(labels)} ({shown})")
    parts.append(f"в приложении обновлено {local_updated}")
    result["message"] = "; ".join(parts) + "."
    return result


def _apply_fbs_source(user, source: dict) -> dict:
    """Скачивает файл склада и применяет остатки только этого склада."""
    label = fbs_source_label(source)
    url = (source.get("stocks_url") or "").strip()
    empty = {
        "ok": False,
        "skipped": False,
        "updated": 0,
        "warehouse_id": str(source.get("warehouse_id") or ""),
        "warehouse_name": source.get("warehouse_name"),
        "total_in_file": 0,
        "matched": 0,
        "changed": 0,
        "ozon_updated": 0,
        "ozon_failed": 0,
        "ozon_deferred": 0,
    }
    if not url:
        return {**empty, "error": f"{label}: не указана ссылка на файл остатков."}

    try:
        stock_map = fetch_fbs_stocks_map(url)
    except Exception as exc:
        return {**empty, "error": f"{label}: {exc}"}

    return _apply_stock_map(user, stock_map, push_to_ozon=True, source=source)


def apply_fbs_stocks_from_content(user, content: bytes, source: dict | None = None) -> dict:
    try:
        stock_map = _parse_workbook(content)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "updated": 0}
    return _apply_stock_map(user, stock_map, push_to_ozon=True, source=source)


def apply_fbs_stocks(user) -> dict:
    """Синхронизация остатков FBS по всем настроенным складам."""
    sources = collect_fbs_sources(user)
    if not sources:
        return {
            "ok": False,
            "skipped": True,
            "updated": 0,
            "error": "Укажите ссылку на файл «Остатки для FBS» в профиле.",
        }

    summary = {
        "ok": True,
        "skipped": False,
        "updated": 0,
        "sources": len(sources),
        "total_in_file": 0,
        "matched": 0,
        "changed": 0,
        "archived": 0,
        "ozon_updated": 0,
        "ozon_failed": 0,
        "ozon_deferred": 0,
        "warehouses": [],
    }
    messages: list[str] = []
    errors: list[str] = []

    for source in sources:
        item = _apply_fbs_source(user, source)
        summary["updated"] += int(item.get("updated") or 0)
        summary["total_in_file"] += int(item.get("total_in_file") or 0)
        summary["matched"] += int(item.get("matched") or 0)
        summary["changed"] += int(item.get("changed") or 0)
        summary["archived"] += int(item.get("archived") or 0)
        summary["ozon_updated"] += int(item.get("ozon_updated") or 0)
        summary["ozon_failed"] += int(item.get("ozon_failed") or 0)
        summary["ozon_deferred"] += int(item.get("ozon_deferred") or 0)

        warehouse_entry = {
            "warehouse_id": item.get("warehouse_id"),
            "warehouse_name": item.get("warehouse_name"),
            "updated": int(item.get("updated") or 0),
            "ozon_updated": int(item.get("ozon_updated") or 0),
            "ok": bool(item.get("ok")),
        }
        if item.get("archived"):
            warehouse_entry["archived"] = int(item["archived"])
        if item.get("archived_items"):
            warehouse_entry["archived_items"] = item["archived_items"]
        message = item.get("message") or item.get("error")
        if message:
            warehouse_entry["message"] = message
            messages.append(message)
        summary["warehouses"].append(warehouse_entry)

        if not item.get("ok"):
            summary["ok"] = False
            if item.get("error"):
                errors.append(str(item["error"]))

    db_session_commit()

    if summary["ok"]:
        if len(messages) == 1 and not summary["archived"]:
            summary["message"] = messages[0]
        else:
            summary["message"] = (
                f"Остатки FBS обновлены по складам: {len(sources)}. "
                f"Локально {summary['updated']}, в Ozon {summary['ozon_updated']}"
                + (
                    f", отложено из-за частоты {summary['ozon_deferred']}"
                    if summary["ozon_deferred"]
                    else ""
                )
                + (
                    f". Пропущено товаров в архиве Ozon: {summary['archived']}"
                    if summary["archived"]
                    else ""
                )
                + "."
            )
        return summary

    summary["error"] = " ".join(errors) or "Не удалось обновить остатки FBS."
    summary["message"] = summary["error"]
    return summary
