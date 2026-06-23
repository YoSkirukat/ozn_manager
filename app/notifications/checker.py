"""Фоновая проверка событий для уведомлений."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from app.extensions import db
from app.models import User
from app.services.notifications_service import get_enabled_notification_slugs
from app.services.order_sync import load_orders_from_ozon
from app.services.supply_sync import load_supplies_from_ozon

logger = logging.getLogger(__name__)

NEW_ORDER_CHECK_DAYS = 1
SHIPMENTS_CHECK_DAYS = 21


def check_notifications_for_user(user: User) -> None:
    if not user.is_active:
        return

    enabled = get_enabled_notification_slugs(user.id)
    if not enabled:
        return

    if "new_order" in enabled:
        _check_new_orders(user)

    if "new_shipment" in enabled or "shipment_status_changed" in enabled:
        _check_shipments(user)

    from app.services.warehouse_slot_monitor import (
        check_warehouse_slot_watches,
        user_has_warehouse_slot_watches,
    )

    if "warehouse_slot_available" in enabled or user_has_warehouse_slot_watches(user.id):
        check_warehouse_slot_watches(user)


def _check_new_orders(user: User) -> None:
    if not user.has_ozon_credentials():
        return

    today = date.today()
    date_from = today - timedelta(days=NEW_ORDER_CHECK_DAYS - 1)
    try:
        result = load_orders_from_ozon(
            user,
            date_from,
            today,
            refresh_financials_batch=False,
        )
        if not result.get("ok"):
            logger.debug(
                "Notification order check failed for user %s: %s",
                user.id,
                result.get("error"),
            )
    except Exception:
        logger.exception("Notification order check error for user %s", user.id)


def _check_shipments(user: User) -> None:
    if not user.has_ozon_credentials():
        return

    today = date.today()
    date_from = today - timedelta(days=SHIPMENTS_CHECK_DAYS - 1)
    try:
        result = load_supplies_from_ozon(user, date_from, today)
        if not result.get("ok"):
            logger.debug(
                "Notification shipments check failed for user %s: %s",
                user.id,
                result.get("error"),
            )
    except Exception:
        logger.exception("Notification shipments check error for user %s", user.id)


def run_notifications_check(app) -> None:
    with app.app_context():
        try:
            user_ids = [
                row[0]
                for row in db.session.query(User.id).filter(User.is_active.is_(True)).all()
            ]
            for user_id in user_ids:
                try:
                    user = db.session.get(User, user_id)
                    if user:
                        check_notifications_for_user(user)
                except Exception:
                    logger.exception("Notification check failed for user %s", user_id)
        except Exception:
            logger.exception("Notifications check job failed")
        finally:
            db.session.remove()
