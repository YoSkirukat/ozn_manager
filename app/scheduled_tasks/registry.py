"""Справочник регламентных заданий и допустимых интервалов."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduleInterval:
    key: str
    label: str


@dataclass(frozen=True)
class ScheduledTaskDef:
    slug: str
    title: str
    description: str
    implemented: bool = False


SCHEDULE_INTERVALS: tuple[ScheduleInterval, ...] = (
    ScheduleInterval("every_1m", "Каждую минуту"),
    ScheduleInterval("every_5m", "Каждые 5 минут"),
    ScheduleInterval("every_30m", "Каждые 30 минут"),
    ScheduleInterval("every_1h", "Каждый час"),
    ScheduleInterval("daily_0100", "Один раз в день (01:00)"),
)

DEFAULT_INTERVAL_KEY = "every_1h"

VALID_INTERVAL_KEYS = frozenset(i.key for i in SCHEDULE_INTERVALS)

SCHEDULED_TASKS: tuple[ScheduledTaskDef, ...] = (
    ScheduledTaskDef(
        slug="orders_sync",
        title="Обновление заказов",
        description="Загрузка заказов FBS/FBO из Ozon за последние 30 дней.",
        implemented=True,
    ),
    ScheduledTaskDef(
        slug="shipments_sync",
        title="Обновление поставок",
        description="Загрузка поставок FBO из Ozon за последние 21 день.",
        implemented=True,
    ),
    ScheduledTaskDef(
        slug="stock_report",
        title="Обновление отчёта по остаткам",
        description="Загрузка актуального среза остатков по складам FBO из Ozon.",
        implemented=True,
    ),
    ScheduledTaskDef(
        slug="fbs_stocks_sync",
        title="Обновление остатков FBS",
        description="Загрузка остатков FBS из Excel и выгрузка в кабинет Ozon через API.",
        implemented=True,
    ),
    ScheduledTaskDef(
        slug="products_sync",
        title="Синхронизация товаров",
        description="Синхронизация каталога товаров, участия в акциях и закупочных цен из Ozon.",
        implemented=True,
    ),
    ScheduledTaskDef(
        slug="returns_check",
        title="Проверка возвратов",
        description="Загрузка возвратов FBO/FBS/realFBS за последние 30 дней.",
        implemented=True,
    ),
)

TASK_BY_SLUG = {t.slug: t for t in SCHEDULED_TASKS}
INTERVAL_LABELS = {i.key: i.label for i in SCHEDULE_INTERVALS}
