from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.services.notifications_service import (
    delete_all_notifications,
    delete_notification,
    get_unread_count,
    list_notification_settings_for_user,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    update_notification_setting,
)

notifications_api_bp = Blueprint("notifications_api", __name__)


@notifications_api_bp.route("/notifications/settings", methods=["GET"])
@login_required
def get_notification_settings():
    return jsonify({
        "ok": True,
        "settings": list_notification_settings_for_user(current_user.id),
    })


@notifications_api_bp.route("/notifications/settings/<event_slug>", methods=["PUT"])
@login_required
def put_notification_setting(event_slug: str):
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled"))
    result = update_notification_setting(current_user.id, event_slug, enabled)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@notifications_api_bp.route("/notifications", methods=["GET"])
@login_required
def get_notifications():
    limit = request.args.get("limit", type=int) or 50
    return jsonify({
        "ok": True,
        "items": list_notifications(current_user.id, limit=limit),
        "unread_count": get_unread_count(current_user.id),
    })


@notifications_api_bp.route("/notifications/unread-count", methods=["GET"])
@login_required
def notifications_unread_count():
    return jsonify({
        "ok": True,
        "unread_count": get_unread_count(current_user.id),
    })


@notifications_api_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def post_notification_read(notification_id: int):
    result = mark_notification_read(current_user.id, notification_id)
    status = 200 if result.get("ok") else 404
    return jsonify(result), status


@notifications_api_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def post_notifications_read_all():
    result = mark_all_notifications_read(current_user.id)
    return jsonify(result)


@notifications_api_bp.route("/notifications/clear-all", methods=["POST"])
@login_required
def post_notifications_clear_all():
    result = delete_all_notifications(current_user.id)
    return jsonify(result)


@notifications_api_bp.route("/notifications/<int:notification_id>", methods=["DELETE"])
@login_required
def delete_notification_route(notification_id: int):
    result = delete_notification(current_user.id, notification_id)
    status = 200 if result.get("ok") else 404
    return jsonify(result), status
