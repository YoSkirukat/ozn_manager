"""Журнал запусков регламентных заданий (без зависимости от планировщика)."""

from __future__ import annotations

from app.db_sqlite import db_session_commit
from app.extensions import db
from app.models import ScheduledTaskRun

TASK_RUN_LOG_LIMIT = 50


def prune_task_run_log(user_id: int, task_slug: str) -> None:
    """Оставляет в журнале задания только последние TASK_RUN_LOG_LIMIT записей."""
    old_ids = [
        row[0]
        for row in db.session.query(ScheduledTaskRun.id)
        .filter_by(user_id=user_id, task_slug=task_slug)
        .order_by(ScheduledTaskRun.started_at.desc())
        .offset(TASK_RUN_LOG_LIMIT)
        .all()
    ]
    if not old_ids:
        return
    ScheduledTaskRun.query.filter(ScheduledTaskRun.id.in_(old_ids)).delete(
        synchronize_session=False,
    )
    db_session_commit()
