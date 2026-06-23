"""Выполнение регламентных заданий."""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from app.db_sqlite import db_session_commit
from app.extensions import db
from app.models import ScheduledTaskRun, User, utcnow
from app.scheduled_tasks.registry import TASK_BY_SLUG
from app.services.order_sync import load_orders_from_ozon
from app.services.product_sync import sync_products_from_ozon
from app.services.scheduled_task_run_log import prune_task_run_log
from app.services.stock_report import load_stock_report, save_stock_report_cache
from app.services.supply_sync import load_supplies_from_ozon
from app.services.returns_report import run_returns_check

logger = logging.getLogger(__name__)

ORDERS_SYNC_DAYS = 30
SHIPMENTS_SYNC_DAYS = 21


def _orders_sync_period() -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=ORDERS_SYNC_DAYS - 1), today


def _shipments_sync_period() -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=SHIPMENTS_SYNC_DAYS - 1), today


def run_scheduled_task(user_id: int, task_slug: str) -> None:
    """Точка входа планировщика (в контексте приложения)."""
    task = TASK_BY_SLUG.get(task_slug)
    if not task or not task.implemented:
        logger.warning(
            "Skip scheduled run %s for user %s: task missing or not implemented",
            task_slug,
            user_id,
        )
        return

    user = db.session.get(User, user_id)
    if not user or not user.is_active:
        return

    run = ScheduledTaskRun(
        user_id=user_id,
        task_slug=task_slug,
        started_at=utcnow(),
        status=ScheduledTaskRun.STATUS_RUNNING,
        details={"pid": os.getpid()},
    )
    db.session.add(run)
    db_session_commit()

    try:
        if task_slug == "orders_sync":
            result = _run_orders_sync(user)
        elif task_slug == "shipments_sync":
            result = _run_shipments_sync(user)
        elif task_slug == "stock_report":
            result = _run_stock_report(user)
        elif task_slug == "products_sync":
            result = _run_products_sync(user)
        elif task_slug == "returns_check":
            result = _run_returns_check(user)
        else:
            result = {"ok": False, "error": "Задание не реализовано."}

        run.finished_at = utcnow()
        if result.get("ok"):
            run.status = ScheduledTaskRun.STATUS_SUCCESS
            run.message = result.get("message") or "Выполнено успешно."
        elif result.get("skipped"):
            run.status = ScheduledTaskRun.STATUS_SKIPPED
            run.message = result.get("error") or "Пропущено."
        else:
            run.status = ScheduledTaskRun.STATUS_ERROR
            run.message = result.get("error") or "Ошибка выполнения."
        run.details = {k: v for k, v in result.items() if k not in ("ok", "message", "error")}
        db_session_commit()
        prune_task_run_log(user_id, task_slug)
    except Exception as exc:
        logger.exception("Scheduled task %s failed for user %s", task_slug, user_id)
        db.session.rollback()
        run.finished_at = utcnow()
        run.status = ScheduledTaskRun.STATUS_ERROR
        run.message = str(exc)
        db_session_commit()
        prune_task_run_log(user_id, task_slug)


def _run_orders_sync(user: User) -> dict:
    if not user.has_ozon_credentials():
        return {
            "ok": False,
            "error": "Подключите Ozon API в профиле.",
            "skipped": True,
        }

    date_from, date_to = _orders_sync_period()
    result = load_orders_from_ozon(
        user,
        date_from,
        date_to,
        refresh_financials_batch=True,
    )
    if result.get("ok"):
        result["message"] = (
            f"Заказы за {date_from.strftime('%d.%m.%Y')}–{date_to.strftime('%d.%m.%Y')}: "
            f"создано {result.get('created', 0)}, обновлено {result.get('updated', 0)}; "
            f"финансы пересчитаны {result.get('financials_updated', 0)}."
        )
        result["date_from"] = date_from.isoformat()
        result["date_to"] = date_to.isoformat()
    return result


def _run_shipments_sync(user: User) -> dict:
    if not user.has_ozon_credentials():
        return {
            "ok": False,
            "error": "Подключите Ozon API в профиле.",
            "skipped": True,
        }

    date_from, date_to = _shipments_sync_period()
    result = load_supplies_from_ozon(user, date_from, date_to)
    if result.get("ok"):
        result["message"] = (
            f"Поставки за {date_from.strftime('%d.%m.%Y')}–{date_to.strftime('%d.%m.%Y')}: "
            f"создано {result.get('created', 0)}, обновлено {result.get('updated', 0)}."
        )
        result["date_from"] = date_from.isoformat()
        result["date_to"] = date_to.isoformat()
    return result


def _run_stock_report(user: User) -> dict:
    if not user.has_ozon_credentials():
        return {
            "ok": False,
            "error": "Подключите Ozon API в профиле.",
            "skipped": True,
        }

    result = load_stock_report(user)
    if result.get("ok"):
        rows = result.get("rows") or []
        save_stock_report_cache(user.id, rows)
        summary = result.get("summary") or {}
        result["message"] = (
            f"Остатки: складов {summary.get('total_warehouses', 0)}, "
            f"SKU {summary.get('total_sku', 0)}, "
            f"единиц {summary.get('total_units', 0)}."
        )
    return result


def _run_products_sync(user: User) -> dict:
    if not user.has_ozon_credentials():
        return {
            "ok": False,
            "error": "Подключите Ozon API в профиле.",
            "skipped": True,
        }

    result = sync_products_from_ozon(user)
    if not result.get("ok"):
        return result

    parts = [
        f"Товары: всего {result.get('total', 0)}, "
        f"создано {result.get('created', 0)}, обновлено {result.get('updated', 0)}.",
    ]
    if result.get("promotions_sync_error"):
        parts.append(f"Акции: {result['promotions_sync_error']}")
    elif result.get("promotions_count") is not None:
        parts.append(
            f"Акции: {result.get('promotions_count', 0)}, "
            f"товаров в акциях {result.get('promotions_product_count', 0)}."
        )
    if result.get("purchase_prices_error"):
        parts.append(f"Закупочные цены: {result['purchase_prices_error']}")
    elif result.get("purchase_prices_updated"):
        parts.append(
            f"Закупочные цены из файла: обновлено {result['purchase_prices_updated']}."
        )
    elif not (user.purchase_prices_url or "").strip():
        parts.append("Закупочные цены: укажите ссылку на файл в профиле.")
    result["message"] = " ".join(parts)
    return result


def _run_returns_check(user: User) -> dict:
    return run_returns_check(user)
