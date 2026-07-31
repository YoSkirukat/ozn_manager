"""Журнал запусков регламентных заданий (без зависимости от планировщика)."""

from __future__ import annotations

import logging

from app.db_sqlite import db_session_run
from app.extensions import db
from app.models import ScheduledTaskRun

logger = logging.getLogger(__name__)

TASK_RUN_LOG_LIMIT = 50


def prune_task_run_log(user_id: int, task_slug: str) -> None:
    """Оставляет в журнале задания только последние TASK_RUN_LOG_LIMIT записей."""

    def _do() -> int:
        old_ids = [
            row[0]
            for row in db.session.query(ScheduledTaskRun.id)
            .filter_by(user_id=user_id, task_slug=task_slug)
            .order_by(ScheduledTaskRun.started_at.desc())
            .offset(TASK_RUN_LOG_LIMIT)
            .all()
        ]
        if not old_ids:
            return 0
        ScheduledTaskRun.query.filter(ScheduledTaskRun.id.in_(old_ids)).delete(
            synchronize_session=False,
        )
        db.session.commit()
        return len(old_ids)

    try:
        db_session_run(_do)
    except Exception:
        # Очистка журнала не должна ронять успешный запуск задания.
        logger.warning(
            "Failed to prune task run log user=%s task=%s",
            user_id,
            task_slug,
            exc_info=True,
        )
