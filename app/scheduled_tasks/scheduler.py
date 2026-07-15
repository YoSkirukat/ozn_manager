"""Встроенный планировщик (APScheduler), без системного cron."""

from __future__ import annotations

import atexit
import fcntl
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import inspect

from app.db_sqlite import db_session_commit
from app.extensions import db
from app.models import ScheduledTaskRun, ScheduledTaskSetting, utcnow
from app.scheduled_tasks.jobs import run_scheduled_task
from app.scheduled_tasks.registry import TASK_BY_SLUG, VALID_INTERVAL_KEYS

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_lock_file = None
_SYNC_JOB_ID = "_sync_scheduled_task_settings"
_NOTIFICATIONS_JOB_ID = "_check_notifications"
_HEARTBEAT_FILE = "scheduler.heartbeat"
_HEARTBEAT_MAX_AGE = 120


def _job_id(user_id: int, task_slug: str) -> str:
    return f"user{user_id}_{task_slug}"


def _build_trigger(interval_key: str, timezone_name: str):
    if interval_key == "every_1m":
        return IntervalTrigger(minutes=1, timezone=timezone_name)
    if interval_key == "every_5m":
        return IntervalTrigger(minutes=5, timezone=timezone_name)
    if interval_key == "every_30m":
        return IntervalTrigger(minutes=30, timezone=timezone_name)
    if interval_key == "every_1h":
        return IntervalTrigger(hours=1, timezone=timezone_name)
    if interval_key == "daily_0100":
        return CronTrigger(hour=1, minute=0, timezone=timezone_name)
    return IntervalTrigger(hours=1, timezone=timezone_name)


def _run_job(user_id: int, task_slug: str, app, interval_key: str | None = None):
    logger.info("Running scheduled task %s for user %s", task_slug, user_id)
    with app.app_context():
        try:
            run_scheduled_task(user_id, task_slug)
        finally:
            db.session.remove()


def _is_schedulable(setting: ScheduledTaskSetting) -> bool:
    if not setting.enabled:
        return False
    if setting.interval_key not in VALID_INTERVAL_KEYS:
        return False
    task = TASK_BY_SLUG.get(setting.task_slug)
    return bool(task and task.implemented)


def _needs_scheduler_lock(app) -> bool:
    """Один планировщик на instance_path (gunicorn, reloader, несколько run.py)."""
    flag = os.environ.get("SCHEDULER_FILE_LOCK", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return True
    return not app.config.get("TESTING")


def _heartbeat_path(instance_path: str) -> Path:
    return Path(instance_path) / _HEARTBEAT_FILE


def _touch_heartbeat(instance_path: str) -> None:
    path = _heartbeat_path(instance_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


def _heartbeat_age_seconds(instance_path: str) -> float | None:
    path = _heartbeat_path(instance_path)
    try:
        raw = path.read_text(encoding="utf-8").strip()
        ts = datetime.fromisoformat(raw)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds()
    except (OSError, ValueError):
        return None


def _scheduler_operational(scheduler) -> bool:
    if not scheduler:
        return False
    running = getattr(scheduler, "running", None)
    return bool(running) if running is not None else True


def _run_owner_pid(run: ScheduledTaskRun) -> int | None:
    details = run.details if isinstance(run.details, dict) else {}
    pid = details.get("pid")
    try:
        return int(pid) if pid is not None else None
    except (TypeError, ValueError):
        return None


def _mark_runs_interrupted(runs: list[ScheduledTaskRun], *, message: str) -> int:
    if not runs:
        return 0
    now = utcnow()
    for run in runs:
        run.status = ScheduledTaskRun.STATUS_ERROR
        run.message = message
        run.finished_at = now
    try:
        db_session_commit()
        return len(runs)
    except Exception:
        db.session.rollback()
        logger.warning("Could not update interrupted scheduled runs", exc_info=True)
        return 0


def _cleanup_stale_running_runs() -> None:
    stale = ScheduledTaskRun.query.filter_by(status=ScheduledTaskRun.STATUS_RUNNING).all()
    if not stale:
        return

    to_mark: list[ScheduledTaskRun] = []
    for run in stale:
        owner_pid = _run_owner_pid(run)
        if owner_pid and _pid_alive(owner_pid):
            continue
        to_mark.append(run)

    marked = _mark_runs_interrupted(
        to_mark,
        message="Прервано при перезапуске приложения.",
    )
    if marked:
        logger.info("Marked %s stale scheduled run(s) as error", marked)


def _mark_own_running_runs_interrupted() -> None:
    pid = os.getpid()
    running = ScheduledTaskRun.query.filter_by(status=ScheduledTaskRun.STATUS_RUNNING).all()
    own = [run for run in running if _run_owner_pid(run) == pid]
    marked = _mark_runs_interrupted(
        own,
        message="Прервано при остановке приложения.",
    )
    if marked:
        logger.info("Marked %s own scheduled run(s) as interrupted on shutdown", marked)


def _on_scheduler_event(event) -> None:
    if event.code == EVENT_JOB_ERROR:
        logger.error("Scheduler job %s failed: %s", event.job_id, event.exception)
    elif event.code == EVENT_JOB_EXECUTED and event.job_id == _SYNC_JOB_ID:
        logger.debug("Scheduler sync job executed")


def schedule_user_task(app, setting: ScheduledTaskSetting) -> None:
    scheduler = app.extensions.get("scheduler")
    if not scheduler:
        return

    job_id = _job_id(setting.user_id, setting.task_slug)
    existing = scheduler.get_job(job_id)
    if existing:
        scheduler.remove_job(job_id)

    if not _is_schedulable(setting):
        return

    tz = app.config.get("SCHEDULER_TIMEZONE", "Europe/Moscow")
    trigger = _build_trigger(setting.interval_key, tz)

    scheduler.add_job(
        _run_job,
        trigger=trigger,
        id=job_id,
        kwargs={
            "user_id": setting.user_id,
            "task_slug": setting.task_slug,
            "app": app,
            "interval_key": setting.interval_key,
        },
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    logger.info("Scheduled job registered: %s (%s)", job_id, setting.interval_key)


def request_reload_jobs(app) -> None:
    """Перечитать настройки из БД и обновить задания планировщика."""
    reload_all_jobs(app)


def get_user_scheduler_jobs(app, user_id: int) -> list[dict]:
    scheduler = app.extensions.get("scheduler")
    if not _scheduler_operational(scheduler):
        return []

    prefix = f"user{user_id}_"
    jobs = []
    for job in sorted(scheduler.get_jobs(), key=lambda j: j.id):
        if not job.id.startswith(prefix):
            continue
        next_run = job.next_run_time.isoformat() if job.next_run_time else None
        jobs.append({"id": job.id, "task_slug": job.id[len(prefix) :], "next_run": next_run})
    return jobs


def get_scheduler_runtime_status(app, user_id: int) -> dict:
    """Статус планировщика для API (только реально работающий)."""
    scheduler = app.extensions.get("scheduler")
    local_ok = _scheduler_operational(scheduler)

    if local_ok:
        return {
            "active": True,
            "local": True,
            "leader_pid": os.getpid(),
            "jobs": get_user_scheduler_jobs(app, user_id),
        }

    age = _heartbeat_age_seconds(app.instance_path)
    if age is not None and age <= _HEARTBEAT_MAX_AGE:
        return {
            "active": True,
            "local": False,
            "leader_pid": _read_lock_pid(_lock_path(app.instance_path)),
            "jobs": [],
        }

    return {
        "active": False,
        "local": False,
        "leader_pid": _read_lock_pid(_lock_path(app.instance_path)),
        "jobs": [],
    }


def _scheduler_tables_ready() -> bool:
    try:
        return "scheduled_task_settings" in inspect(db.engine).get_table_names()
    except Exception:
        return False


def reload_all_jobs(app) -> None:
    scheduler = app.extensions.get("scheduler")
    if not _scheduler_operational(scheduler):
        return

    if not _scheduler_tables_ready():
        logger.info("Scheduled task tables not ready; skip loading jobs.")
        return

    settings = ScheduledTaskSetting.query.filter_by(enabled=True).all()
    desired: dict[str, ScheduledTaskSetting] = {}
    for setting in settings:
        if not _is_schedulable(setting):
            continue
        desired[_job_id(setting.user_id, setting.task_slug)] = setting

    for job in list(scheduler.get_jobs()):
        if job.id.startswith("user") and job.id not in desired:
            scheduler.remove_job(job.id)

    scheduled = 0
    for job_id, setting in desired.items():
        existing = scheduler.get_job(job_id)
        if existing and existing.kwargs.get("interval_key") == setting.interval_key:
            continue
        schedule_user_task(app, setting)
        scheduled += 1

    _touch_heartbeat(app.instance_path)
    logger.info(
        "Scheduled tasks sync: %s new/updated job(s), %s active in scheduler",
        scheduled,
        len(desired),
    )


def _sync_jobs_from_db(app) -> None:
    with app.app_context():
        try:
            reload_all_jobs(app)
        finally:
            db.session.remove()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _lock_path(instance_path: str) -> Path:
    return Path(instance_path) / "scheduler.lock"


def _read_lock_pid(lock_path: Path) -> int | None:
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def _clear_stale_lock_file(instance_path: str) -> None:
    lock_path = _lock_path(instance_path)
    pid = _read_lock_pid(lock_path)
    if pid and _pid_alive(pid):
        return
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def _try_acquire_lock(instance_path: str) -> bool:
    global _lock_file
    lock_path = _lock_path(instance_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    existing_pid = _read_lock_pid(lock_path)
    if existing_pid and _pid_alive(existing_pid):
        return False
    if lock_path.exists():
        try:
            lock_path.unlink()
        except OSError:
            pass

    handle = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        _lock_file = handle
        return True
    except BlockingIOError:
        handle.close()
        return False
    except OSError:
        handle.close()
        return False


def is_scheduler_leader_running(instance_path: str) -> bool:
    pid = _read_lock_pid(_lock_path(instance_path))
    return bool(pid and _pid_alive(pid))


def _should_start(app) -> bool:
    if not app.config.get("SCHEDULER_ENABLED", True):
        return False
    if app.config.get("TESTING"):
        return False
    if os.environ.get("DISABLE_SCHEDULER") == "1":
        return False
    if app.debug and os.environ.get("FLASK_USE_RELOADER", "1") == "1":
        if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
            return False
    return True


def _start_scheduler(app) -> None:
    global _scheduler

    tz = app.config.get("SCHEDULER_TIMEZONE", "Europe/Moscow")
    # default — регламентные задания; notifications — отдельный пул,
    # чтобы долгие sync-ы не блокировали мониторинг складов.
    scheduler = BackgroundScheduler(
        timezone=tz,
        executors={
            "default": ThreadPoolExecutor(max_workers=3),
            "notifications": ThreadPoolExecutor(max_workers=1),
        },
        job_defaults={"coalesce": True, "max_instances": 1},
    )
    scheduler.add_listener(_on_scheduler_event, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)
    scheduler.start()
    app.extensions["scheduler"] = scheduler
    _scheduler = scheduler

    with app.app_context():
        _cleanup_stale_running_runs()
        reload_all_jobs(app)

    sync_seconds = int(app.config.get("SCHEDULER_SYNC_SECONDS", 30))
    scheduler.add_job(
        _sync_jobs_from_db,
        trigger=IntervalTrigger(seconds=sync_seconds, timezone=tz),
        id=_SYNC_JOB_ID,
        kwargs={"app": app},
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    from app.notifications.checker import run_notifications_check

    scheduler.add_job(
        run_notifications_check,
        trigger=IntervalTrigger(minutes=1, timezone=tz),
        id=_NOTIFICATIONS_JOB_ID,
        kwargs={"app": app},
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        executor="notifications",
    )

    _touch_heartbeat(app.instance_path)
    user_jobs = [j.id for j in scheduler.get_jobs() if j.id.startswith("user")]
    logger.info(
        "Background scheduler started (pid=%s, timezone=%s, jobs=%s)",
        os.getpid(),
        tz,
        user_jobs,
    )


def init_scheduler(app) -> None:
    global _scheduler

    if not _should_start(app):
        logger.info("Scheduler disabled for this process (pid=%s)", os.getpid())
        return
    if app.extensions.get("scheduler"):
        return

    if _needs_scheduler_lock(app):
        if not _try_acquire_lock(app.instance_path):
            logger.info(
                "Scheduler lock held by another process (pid=%s); skipping start.",
                os.getpid(),
            )
            return
    else:
        _clear_stale_lock_file(app.instance_path)

    try:
        _start_scheduler(app)
    except Exception:
        logger.exception("Failed to start background scheduler")
        raise

    atexit.register(lambda: _shutdown_scheduler(app))


def _shutdown_scheduler(app) -> None:
    global _scheduler, _lock_file
    try:
        with app.app_context():
            _mark_own_running_runs_interrupted()
    except Exception:
        logger.warning("Failed to mark running tasks on scheduler shutdown", exc_info=True)
    scheduler = app.extensions.pop("scheduler", None)
    if scheduler:
        scheduler.shutdown(wait=False)
    _scheduler = None
    if _lock_file:
        try:
            fcntl.flock(_lock_file.fileno(), fcntl.LOCK_UN)
            _lock_file.close()
        except OSError:
            pass
        _lock_file = None
