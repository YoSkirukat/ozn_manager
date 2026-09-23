"""Действия с отправлениями FBS в Ozon (сборка заказа)."""

from __future__ import annotations

import json
import re

from app.datetime_fmt import utc_bounds_for_local_dates
from app.db_sqlite import db_session_commit
from app.models import LABEL_DOWNLOADED_RAW_KEY, Order, utcnow
from app.ozon.orders import (
    fetch_fbs_package_label,
    posting_status_from_response,
    ship_fbs_posting,
)
from app.services.change_log import log_change
from app.services.fbs_orders import FBS_NEW_STATUSES
from app.services.order_details import fetch_posting_detail, merge_order_raw_data

ASSEMBLE_TARGET_STATUS = "awaiting_deliver"
SHIP_ACTIONS = frozenset({"ship", "ship_async"})

# Сколько «новых» заказов за один раз догружать детально из Ozon (статус, трек, действия).
DETAIL_REFRESH_LIMIT = 50


def _shipping_products(order: Order) -> list[dict]:
    """Товары отправления для сборки: product_id (= sku) и количество."""
    raw = order.raw_data if isinstance(order.raw_data, dict) else {}
    financial = raw.get("financial_data")
    fin_products = financial.get("products") if isinstance(financial, dict) else None
    fin_rows = [row for row in fin_products if isinstance(row, dict)] if isinstance(fin_products, list) else []

    products: list[dict] = []
    for index, item in enumerate(raw.get("products") or []):
        if not isinstance(item, dict):
            continue

        fin = fin_rows[index] if index < len(fin_rows) else {}
        product_id = item.get("sku") or item.get("product_id") or fin.get("product_id") or fin.get("sku")
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            continue

        try:
            quantity = int(item.get("quantity") or fin.get("quantity") or 1)
        except (TypeError, ValueError):
            quantity = 1
        products.append({"product_id": product_id, "quantity": max(quantity, 1)})
    return products


def _raw_without_ship_actions(order: Order, new_status: str) -> dict:
    """Снимает действия сборки, если детали отправления из Ozon получить не удалось."""
    raw = dict(order.raw_data) if isinstance(order.raw_data, dict) else {}
    actions = raw.get("available_actions")
    if isinstance(actions, list):
        raw["available_actions"] = [action for action in actions if action not in SHIP_ACTIONS]
    raw["status"] = new_status
    return raw


def _humanize_error(exc: Exception) -> str:
    """Текст ошибки Ozon без технической обёртки клиента."""
    text = str(exc)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group(0))
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            message = str(payload.get("message") or "").strip()
            if message:
                return f"Ozon: {message}"
    return text or "Не удалось собрать заказ в Ozon."


def assemble_fbs_order(user, order: Order) -> dict:
    """Собирает отправление FBS в Ozon: статус становится «Ожидает отгрузки»."""
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Укажите Client-Id и Api-Key в профиле."}
    if (order.scheme or "").upper() != Order.SCHEME_FBS:
        return {"ok": False, "error": "Сборка доступна только для заказов FBS."}
    if not order.can_assemble_fbs():
        return {"ok": False, "error": "Заказ уже нельзя собрать — обновите список заказов."}

    products = _shipping_products(order)
    if not products:
        return {"ok": False, "error": "В отправлении нет товаров для сборки."}

    try:
        response = ship_fbs_posting(
            user.ozon_client_id,
            user.ozon_api_key,
            order.ozon_order_id,
            products,
        )
    except Exception as exc:  # noqa: BLE001 — текст ошибки показываем пользователю
        return {"ok": False, "error": _humanize_error(exc)}

    old_status = order.status
    try:
        detail = fetch_posting_detail(user, order.ozon_order_id, order.scheme)
    except Exception:  # noqa: BLE001 — статус можно взять из ответа сборки
        detail = None

    new_status = str((detail or {}).get("status") or "").strip()
    if not new_status:
        new_status = posting_status_from_response(response, order.ozon_order_id) or ASSEMBLE_TARGET_STATUS

    if isinstance(detail, dict) and detail:
        order.raw_data = merge_order_raw_data(
            order.raw_data,
            detail,
            old_status=old_status,
            new_status=new_status,
        )
    else:
        order.raw_data = _raw_without_ship_actions(order, new_status)
    order.status = new_status

    log_change(
        user_id=user.id,
        action_type="update",
        entity_type="order",
        entity_id=order.id,
        old_value={"status": old_status},
        new_value={"status": new_status, "action": "fbs_assemble"},
    )
    db_session_commit()

    return {
        "ok": True,
        "posting_number": order.ozon_order_id,
        "status": new_status,
        "status_display": order.status_display(),
        "message": f"Заказ {order.ozon_order_id} собран: статус «{order.status_display()}».",
    }


def refresh_new_fbs_details(user, date_from, date_to) -> int:
    """Догружает детали «новых» FBS-заказов: статус, трек-номер, доступные действия."""
    start, end = utc_bounds_for_local_dates(date_from, date_to)
    orders = (
        Order.query.filter(
            Order.user_id == user.id,
            Order.scheme == Order.SCHEME_FBS,
            Order.status.in_(FBS_NEW_STATUSES),
            Order.order_date >= start,
            Order.order_date <= end,
        )
        .order_by(Order.order_date.desc())
        .limit(DETAIL_REFRESH_LIMIT)
        .all()
    )

    refreshed = 0
    for order in orders:
        try:
            detail = fetch_posting_detail(user, order.ozon_order_id, order.scheme)
        except Exception:  # noqa: BLE001 — детали не критичны для обновления списка
            continue
        if not detail:
            continue

        old_status = order.status
        new_status = str(detail.get("status") or "").strip() or old_status
        order.raw_data = merge_order_raw_data(
            order.raw_data,
            detail,
            old_status=old_status,
            new_status=new_status,
        )
        order.status = new_status
        refreshed += 1

    if refreshed:
        db_session_commit()
    return refreshed


def refresh_fbs_orders(user, date_from, date_to) -> dict:
    """Обновляет заказы из Ozon: список, статусы, трек-номера и доступные действия."""
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Укажите Client-Id и Api-Key в профиле."}

    from app.services.order_sync import load_orders_from_ozon

    sync = load_orders_from_ozon(user, date_from, date_to, refresh_financials_batch=False)
    if not sync.get("ok"):
        return {"ok": False, "error": sync.get("error") or "Не удалось обновить заказы."}

    details_refreshed = refresh_new_fbs_details(user, date_from, date_to)

    return {
        "ok": True,
        "total": sync.get("total", 0),
        "created": sync.get("created", 0),
        "updated": sync.get("updated", 0),
        "fbs": sync.get("fbs", 0),
        "details_refreshed": details_refreshed,
        "message": (
            f"Заказы обновлены из Ozon: загружено {sync.get('total', 0)} "
            f"(FBS {sync.get('fbs', 0)}), новых {sync.get('created', 0)}; "
            f"статусы новых FBS обновлены: {details_refreshed}."
        ),
    }


def load_fbs_label(user, order: Order) -> dict:
    """PDF-этикетка отправления FBS для скачивания."""
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Укажите Client-Id и Api-Key в профиле."}
    if (order.scheme or "").upper() != Order.SCHEME_FBS:
        return {"ok": False, "error": "Этикетка доступна только для заказов FBS."}
    if not order.can_download_label():
        return {"ok": False, "error": "Этикетка станет доступна после сборки заказа."}

    try:
        content = fetch_fbs_package_label(
            user.ozon_client_id,
            user.ozon_api_key,
            order.ozon_order_id,
        )
    except Exception as exc:  # noqa: BLE001 — текст ошибки показываем пользователю
        return {"ok": False, "error": _humanize_error(exc)}

    if not content:
        return {"ok": False, "error": "Ozon не вернул файл этикетки."}

    raw = dict(order.raw_data) if isinstance(order.raw_data, dict) else {}
    raw[LABEL_DOWNLOADED_RAW_KEY] = utcnow().isoformat()
    order.raw_data = raw
    db_session_commit()

    return {
        "ok": True,
        "content": content,
        "filename": f"label-{order.ozon_order_id}.pdf",
        "downloaded_at": raw[LABEL_DOWNLOADED_RAW_KEY],
    }
