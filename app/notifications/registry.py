"""Реестр типов уведомлений."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationEvent:
    slug: str
    title: str
    description: str
    implemented: bool = True


NOTIFICATION_EVENTS: tuple[NotificationEvent, ...] = (
    NotificationEvent(
        slug="new_order",
        title="Новый заказ",
        description="Уведомление при появлении нового заказа из Ozon.",
        implemented=True,
    ),
    NotificationEvent(
        slug="new_shipment",
        title="Новая поставка",
        description="Уведомление при создании новой заявки на поставку FBO.",
        implemented=True,
    ),
    NotificationEvent(
        slug="shipment_status_changed",
        title="Изменение статуса поставки",
        description="Уведомление при смене статуса заявки на поставку.",
        implemented=True,
    ),
    NotificationEvent(
        slug="warehouse_slot_available",
        title="Склад доступен к поставке",
        description="Уведомление, когда отслеживаемый склад доступен для поставки FBO.",
        implemented=True,
    ),
)

EVENT_BY_SLUG = {event.slug: event for event in NOTIFICATION_EVENTS}
