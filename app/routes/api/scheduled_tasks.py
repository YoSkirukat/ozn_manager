from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.services.scheduled_task_run_log import TASK_RUN_LOG_LIMIT
from app.services.scheduled_tasks_service import (
    get_interval_options,
    get_scheduler_status,
    list_task_runs,
    list_tasks_for_user,
    run_task_manually,
    update_task_setting,
)
from app.scheduled_tasks.registry import TASK_BY_SLUG

scheduled_tasks_api_bp = Blueprint("scheduled_tasks_api", __name__)


@scheduled_tasks_api_bp.route("/profile/scheduled-tasks", methods=["GET"])
@login_required
def get_scheduled_tasks():
    return jsonify({
        "ok": True,
        "tasks": list_tasks_for_user(current_user.id),
        "intervals": get_interval_options(),
        "scheduler": get_scheduler_status(current_user.id),
    })


@scheduled_tasks_api_bp.route("/profile/scheduled-tasks/<task_slug>", methods=["PUT"])
@login_required
def put_scheduled_task(task_slug: str):
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled"))
    interval_key = (data.get("interval_key") or "").strip()
    result = update_task_setting(current_user.id, task_slug, enabled, interval_key)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@scheduled_tasks_api_bp.route("/profile/scheduled-tasks/<task_slug>/run", methods=["POST"])
@login_required
def run_scheduled_task_now(task_slug: str):
    result = run_task_manually(current_user.id, task_slug)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@scheduled_tasks_api_bp.route("/profile/scheduled-tasks/runs", methods=["GET"])
@login_required
def get_scheduled_task_runs():
    task_slug = (request.args.get("task_slug") or "").strip()
    if not task_slug or task_slug not in TASK_BY_SLUG:
        return jsonify({"ok": False, "error": "Укажите задание."}), 400

    return jsonify({
        "ok": True,
        "task_slug": task_slug,
        "task_title": TASK_BY_SLUG[task_slug].title,
        "limit": TASK_RUN_LOG_LIMIT,
        "runs": list_task_runs(current_user.id, task_slug),
    })
