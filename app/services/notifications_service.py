"""Уведомления: настройки, создание и управление."""

from __future__ import annotations

import time

from app.db_sqlite import db_session_commit
from app.extensions import db
from app.models import Notification, NotificationSetting, Order, Shipment, SUPPLY_STATUS_LABELS, utcnow
from app.notifications.registry import EVENT_BY_SLUG, NOTIFICATION_EVENTS

NOTIFICATION_LIST_LIMIT = 50


def ensure_user_notification_settings(user_id: int) -> None:
    existing = {
        row.event_slug
        for row in NotificationSetting.query.filter_by(user_id=user_id).all()
    }
    for event in NOTIFICATION_EVENTS:
        if event.slug in existing:
            continue
        db.session.add(
            NotificationSetting(
                user_id=user_id,
                event_slug=event.slug,
                enabled=True,
            )
        )
    db.session.commit()


def list_notification_settings_for_user(user_id: int) -> list[dict]:
    ensure_user_notification_settings(user_id)
    settings = {
        row.event_slug: row
        for row in NotificationSetting.query.filter_by(user_id=user_id).all()
    }
    items = []
    for event in NOTIFICATION_EVENTS:
        setting = settings[event.slug]
        items.append(
            {
                "slug": event.slug,
                "title": event.title,
                "description": event.description,
                "implemented": event.implemented,
                "enabled": setting.enabled,
            }
        )
    return items


def update_notification_setting(user_id: int, event_slug: str, enabled: bool) -> dict:
    event = EVENT_BY_SLUG.get(event_slug)
    if not event:
        return {"ok": False, "error": "Неизвестный тип уведомления."}
    if not event.implemented:
        return {"ok": False, "error": "Этот тип уведомлений пока недоступен."}

    ensure_user_notification_settings(user_id)
    setting = NotificationSetting.query.filter_by(
        user_id=user_id,
        event_slug=event_slug,
    ).first()
    if not setting:
        return {"ok": False, "error": "Настройка не найдена."}

    setting.enabled = bool(enabled)
    db_session_commit()
    return {"ok": True, "enabled": setting.enabled}


def is_notification_enabled(user_id: int, event_slug: str) -> bool:
    ensure_user_notification_settings(user_id)
    setting = NotificationSetting.query.filter_by(
        user_id=user_id,
        event_slug=event_slug,
    ).first()
    return bool(setting and setting.enabled)


def get_enabled_notification_slugs(user_id: int) -> set[str]:
    ensure_user_notification_settings(user_id)
    rows = NotificationSetting.query.filter_by(user_id=user_id, enabled=True).all()
    return {row.event_slug for row in rows if row.event_slug in EVENT_BY_SLUG}


def _notification_entity_id(entity_id: int, *, dedupe_key: str | None = None) -> int:
    if not dedupe_key:
        return int(entity_id)
    digest = abs(hash(f"{entity_id}:{dedupe_key}")) % 2_147_483_646
    return max(1, digest)


def create_notification(
    user_id: int,
    *,
    event_slug: str,
    title: str,
    body: str,
    target_url: str,
    entity_type: str = "",
    entity_id: int = 0,
    payload: dict | None = None,
    dedupe_key: str | None = None,
) -> Notification | None:
    if not is_notification_enabled(user_id, event_slug):
        return None

    storage_entity_id = _notification_entity_id(entity_id, dedupe_key=dedupe_key)
    exists = Notification.query.filter_by(
        user_id=user_id,
        event_slug=event_slug,
        entity_type=entity_type,
        entity_id=storage_entity_id,
    ).first()
    if exists:
        return None

    notification = Notification(
        user_id=user_id,
        event_slug=event_slug,
        title=title,
        body=body,
        target_url=target_url,
        entity_type=entity_type,
        entity_id=storage_entity_id,
        payload=payload or {},
        created_at=utcnow(),
    )
    db.session.add(notification)
    db_session_commit()
    return notification


def notify_new_orders(user, orders: list[Order]) -> int:
    if not orders:
        return 0
    if not is_notification_enabled(user.id, "new_order"):
        return 0

    from app.money_fmt import format_money_ru

    created = 0
    for order in orders:
        total_text = format_money_ru(order.total)
        scheme = order.scheme_display()
        status = order.status_display()
        posting = order.ozon_order_id
        body = f"{scheme} · {status} · {total_text}"
        notification = create_notification(
            user.id,
            event_slug="new_order",
            title=f"Новый заказ {posting}",
            body=body,
            target_url=f"/orders?posting={posting}",
            entity_type="order",
            entity_id=int(order.id),
            payload={
                "order_id": order.id,
                "ozon_order_id": posting,
                "scheme": scheme,
                "status": order.status,
                "total": float(order.total or 0),
            },
        )
        if notification:
            created += 1
    return created


def notify_new_shipments(user, shipments: list[Shipment]) -> int:
    if not shipments:
        return 0
    if not is_notification_enabled(user.id, "new_shipment"):
        return 0

    created = 0
    for shipment in shipments:
        number = shipment.order_number or shipment.ozon_supply_id
        warehouse = shipment.warehouse_name or "—"
        status = shipment.status_display()
        body = f"{status} · {warehouse}"
        notification = create_notification(
            user.id,
            event_slug="new_shipment",
            title=f"Новая поставка {number}",
            body=body,
            target_url=f"/shipments?shipment_id={shipment.id}",
            entity_type="shipment",
            entity_id=int(shipment.id),
            payload={
                "shipment_id": shipment.id,
                "ozon_supply_id": shipment.ozon_supply_id,
                "order_number": shipment.order_number,
                "status": shipment.status,
                "warehouse_name": shipment.warehouse_name,
            },
        )
        if notification:
            created += 1
    return created


def notify_shipment_status_changed(user, shipment: Shipment, old_status: str) -> int:
    if not is_notification_enabled(user.id, "shipment_status_changed"):
        return 0

    new_status = str(shipment.status or "")
    old_status = str(old_status or "")
    if not new_status or old_status == new_status:
        return 0

    number = shipment.order_number or shipment.ozon_supply_id
    old_label = SUPPLY_STATUS_LABELS.get(old_status, old_status)
    new_label = shipment.status_display()
    warehouse = shipment.warehouse_name or "—"
    body = f"{old_label} → {new_label} · {warehouse}"

    notification = create_notification(
        user.id,
        event_slug="shipment_status_changed",
        title=f"Поставка {number}: смена статуса",
        body=body,
        target_url=f"/shipments?shipment_id={shipment.id}",
        entity_type="shipment",
        entity_id=int(shipment.id),
        dedupe_key=f"{old_status}->{new_status}",
        payload={
            "shipment_id": shipment.id,
            "ozon_supply_id": shipment.ozon_supply_id,
            "order_number": shipment.order_number,
            "old_status": old_status,
            "new_status": new_status,
            "warehouse_name": shipment.warehouse_name,
        },
    )
    return 1 if notification else 0


def _return_entity_id(return_id: str) -> int:
    digest = abs(hash(str(return_id or ""))) % 2_147_483_646
    return max(1, digest)


def notify_new_returns(user, returns: list[dict]) -> int:
    if not returns:
        return 0
    if not is_notification_enabled(user.id, "new_return"):
        return 0

    created = 0
    for item in returns:
        return_id = str(item.get("return_id") or "")
        if not return_id:
            continue
        number = str(item.get("application_number") or return_id)
        scheme = str(item.get("scheme") or "—")
        status = str(item.get("status") or "—")
        reason = str(item.get("reason") or "—")
        body = f"{scheme} · {status} · {reason}"
        notification = create_notification(
            user.id,
            event_slug="new_return",
            title=f"Новый возврат {number}",
            body=body,
            target_url="/reports/returns",
            entity_type="return",
            entity_id=_return_entity_id(return_id),
            payload={
                "return_id": return_id,
                "application_number": number,
                "scheme": scheme,
                "status": status,
                "reason": reason,
                "posting_number": str(item.get("posting_number") or ""),
            },
        )
        if notification:
            created += 1
    return created


def notify_return_status_changed(user, item: dict, old_status: str) -> int:
    if not is_notification_enabled(user.id, "return_status_changed"):
        return 0

    return_id = str(item.get("return_id") or "")
    if not return_id:
        return 0

    new_status = str(item.get("status") or "")
    old_status = str(old_status or "")
    if not new_status or old_status == new_status:
        return 0

    number = str(item.get("application_number") or return_id)
    scheme = str(item.get("scheme") or "—")
    body = f"{old_status} → {new_status} · {scheme}"

    notification = create_notification(
        user.id,
        event_slug="return_status_changed",
        title=f"Возврат {number}: смена статуса",
        body=body,
        target_url="/reports/returns",
        entity_type="return",
        entity_id=_return_entity_id(return_id),
        dedupe_key=f"{old_status}->{new_status}",
        payload={
            "return_id": return_id,
            "application_number": number,
            "scheme": scheme,
            "old_status": old_status,
            "new_status": new_status,
            "posting_number": str(item.get("posting_number") or ""),
        },
    )
    return 1 if notification else 0


def notify_warehouse_slot_available(user, watch, warehouse_row: dict) -> int:
    if not is_notification_enabled(user.id, "warehouse_slot_available"):
        return 0

    warehouse_name = str(warehouse_row.get("name") or watch.warehouse_name or "—")
    cluster_name = str(warehouse_row.get("cluster_name") or watch.cluster_name or "—")
    state_label = str(warehouse_row.get("availability_label") or "Доступен")
    body = f"{state_label} · {cluster_name}"

    notification = create_notification(
        user.id,
        event_slug="warehouse_slot_available",
        title=f"Склад {warehouse_name} доступен к поставке",
        body=body,
        target_url="/analytics/warehouse-slots",
        entity_type="warehouse_slot",
        entity_id=int(watch.storage_warehouse_id),
        dedupe_key=f"available:{int(time.time())}",
        payload={
            "watch_id": watch.id,
            "storage_warehouse_id": watch.storage_warehouse_id,
            "macrolocal_cluster_id": watch.macrolocal_cluster_id,
            "cluster_id": watch.cluster_id,
            "warehouse_name": warehouse_name,
            "cluster_name": cluster_name,
            "availability_state": warehouse_row.get("availability_state"),
        },
    )
    return 1 if notification else 0


def list_notifications(user_id: int, *, limit: int = NOTIFICATION_LIST_LIMIT) -> list[dict]:
    rows = (
        Notification.query.filter_by(user_id=user_id)
        .order_by(Notification.created_at.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    return [row.to_dict() for row in rows]


def get_unread_count(user_id: int) -> int:
    return Notification.query.filter_by(user_id=user_id, read_at=None).count()


def mark_notification_read(user_id: int, notification_id: int) -> dict:
    notification = Notification.query.filter_by(
        user_id=user_id,
        id=notification_id,
    ).first()
    if not notification:
        return {"ok": False, "error": "Уведомление не найдено."}
    if notification.read_at is None:
        notification.read_at = utcnow()
        db_session_commit()
    return {"ok": True, "notification": notification.to_dict()}


def mark_all_notifications_read(user_id: int) -> dict:
    now = utcnow()
    updated = (
        Notification.query.filter_by(user_id=user_id, read_at=None)
        .update({"read_at": now}, synchronize_session=False)
    )
    db_session_commit()
    return {"ok": True, "updated": updated}


def delete_all_notifications(user_id: int) -> dict:
    deleted = (
        Notification.query.filter_by(user_id=user_id)
        .delete(synchronize_session=False)
    )
    db_session_commit()
    return {"ok": True, "deleted": deleted}


def delete_notification(user_id: int, notification_id: int) -> dict:
    notification = Notification.query.filter_by(
        user_id=user_id,
        id=notification_id,
    ).first()
    if not notification:
        return {"ok": False, "error": "Уведомление не найдено."}
    db.session.delete(notification)
    db_session_commit()
    return {"ok": True}
