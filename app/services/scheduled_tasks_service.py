"""Настройки и журнал регламентных заданий."""

from __future__ import annotations

from flask import current_app

from app.extensions import db
from app.models import ScheduledTaskRun, ScheduledTaskSetting, User
from app.scheduled_tasks.registry import (
    DEFAULT_INTERVAL_KEY,
    INTERVAL_LABELS,
    SCHEDULED_TASKS,
    SCHEDULE_INTERVALS,
    TASK_BY_SLUG,
    VALID_INTERVAL_KEYS,
)
from app.datetime_fmt import to_iso_utc
from app.scheduled_tasks.scheduler import get_scheduler_runtime_status, request_reload_jobs
from app.services.scheduled_task_run_log import TASK_RUN_LOG_LIMIT


def ensure_user_task_settings(user_id: int) -> None:
    existing = {
        row.task_slug
        for row in ScheduledTaskSetting.query.filter_by(user_id=user_id).all()
    }
    for task in SCHEDULED_TASKS:
        if task.slug in existing:
            continue
        db.session.add(
            ScheduledTaskSetting(
                user_id=user_id,
                task_slug=task.slug,
                enabled=False,
                interval_key=DEFAULT_INTERVAL_KEY,
            )
        )
    db.session.commit()


def list_tasks_for_user(user_id: int) -> list[dict]:
    ensure_user_task_settings(user_id)
    settings = {
        s.task_slug: s
        for s in ScheduledTaskSetting.query.filter_by(user_id=user_id).all()
    }
    items = []
    for task in SCHEDULED_TASKS:
        setting = settings[task.slug]
        items.append(
            {
                "slug": task.slug,
                "title": task.title,
                "description": task.description,
                "implemented": task.implemented,
                "enabled": setting.enabled,
                "interval_key": setting.interval_key,
                "interval_label": INTERVAL_LABELS.get(setting.interval_key, setting.interval_key),
            }
        )
    return items


def get_interval_options() -> list[dict]:
    return [{"key": i.key, "label": i.label} for i in SCHEDULE_INTERVALS]


def get_scheduler_status(user_id: int) -> dict:
    app = current_app._get_current_object()
    return get_scheduler_runtime_status(app, user_id)


def update_task_setting(user_id: int, task_slug: str, enabled: bool, interval_key: str) -> dict:
    task = TASK_BY_SLUG.get(task_slug)
    if not task:
        return {"ok": False, "error": "Неизвестное задание."}
    if not task.implemented:
        return {"ok": False, "error": "Это задание пока недоступно."}
    if interval_key not in VALID_INTERVAL_KEYS:
        return {"ok": False, "error": "Недопустимая периодичность."}

    ensure_user_task_settings(user_id)
    setting = ScheduledTaskSetting.query.filter_by(
        user_id=user_id,
        task_slug=task_slug,
    ).first()
    if not setting:
        return {"ok": False, "error": "Настройка не найдена."}

    setting.enabled = enabled and task.implemented
    setting.interval_key = interval_key
    db.session.commit()

    app = current_app._get_current_object()
    request_reload_jobs(app)

    return {
        "ok": True,
        "task": {
            "slug": task_slug,
            "enabled": setting.enabled,
            "interval_key": setting.interval_key,
            "interval_label": INTERVAL_LABELS.get(setting.interval_key, setting.interval_key),
        },
    }


def list_task_runs(
    user_id: int,
    task_slug: str,
    limit: int = TASK_RUN_LOG_LIMIT,
) -> list[dict]:
    limit = min(max(limit, 1), TASK_RUN_LOG_LIMIT)
    runs = (
        ScheduledTaskRun.query.filter_by(user_id=user_id, task_slug=task_slug)
        .order_by(ScheduledTaskRun.started_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for run in runs:
        task = TASK_BY_SLUG.get(run.task_slug)
        result.append(
            {
                "id": run.id,
                "task_slug": run.task_slug,
                "task_title": task.title if task else run.task_slug,
                "started_at": to_iso_utc(run.started_at),
                "finished_at": to_iso_utc(run.finished_at),
                "status": run.status,
                "message": run.message,
                "details": run.details,
            }
        )
    return result


def run_task_manually(user_id: int, task_slug: str) -> dict:
    task = TASK_BY_SLUG.get(task_slug)
    if not task:
        return {"ok": False, "error": "Неизвестное задание."}
    if not task.implemented:
        return {"ok": False, "error": "Это задание пока недоступно."}

    running = (
        ScheduledTaskRun.query.filter_by(
            user_id=user_id,
            task_slug=task_slug,
            status=ScheduledTaskRun.STATUS_RUNNING,
        )
        .first()
    )
    if running:
        return {"ok": False, "error": "Задание уже выполняется. Дождитесь завершения."}

    from app.scheduled_tasks.jobs import run_scheduled_task

    run_scheduled_task(user_id, task_slug)

    last_run = (
        ScheduledTaskRun.query.filter_by(user_id=user_id, task_slug=task_slug)
        .order_by(ScheduledTaskRun.started_at.desc())
        .first()
    )
    if not last_run:
        return {"ok": False, "error": "Не удалось получить результат запуска."}

    run_payload = {
        "id": last_run.id,
        "task_slug": last_run.task_slug,
        "task_title": task.title,
        "started_at": to_iso_utc(last_run.started_at),
        "finished_at": to_iso_utc(last_run.finished_at),
        "status": last_run.status,
        "message": last_run.message,
        "details": last_run.details,
    }

    if last_run.status == ScheduledTaskRun.STATUS_SUCCESS:
        return {"ok": True, "run": run_payload, "message": last_run.message or "Выполнено успешно."}
    if last_run.status == ScheduledTaskRun.STATUS_SKIPPED:
        return {
            "ok": False,
            "error": last_run.message or "Задание пропущено.",
            "run": run_payload,
        }
    return {
        "ok": False,
        "error": last_run.message or "Ошибка выполнения.",
        "run": run_payload,
    }
