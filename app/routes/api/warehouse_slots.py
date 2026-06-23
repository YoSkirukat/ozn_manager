from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.services.warehouse_slots import (
    get_warehouse_timeslots,
    list_macrolocal_clusters,
    refresh_warehouse_availability,
)
from app.services.warehouse_slot_monitor import (
    add_warehouse_slot_watch,
    list_warehouse_slot_watches,
    remove_warehouse_slot_watch,
)

warehouse_slots_api_bp = Blueprint("warehouse_slots_api", __name__)


def _parse_int(value, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@warehouse_slots_api_bp.route("/analytics/warehouse-slots/clusters", methods=["GET"])
@login_required
def warehouse_slots_clusters():
    result = list_macrolocal_clusters(current_user)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@warehouse_slots_api_bp.route("/analytics/warehouse-slots/refresh", methods=["POST"])
@login_required
def warehouse_slots_refresh():
    payload = request.get_json(silent=True) or {}
    macrolocal_cluster_id = _parse_int(payload.get("macrolocal_cluster_id"), "macrolocal_cluster_id")
    cluster_id = _parse_int(payload.get("cluster_id"), "cluster_id")
    force = bool(payload.get("force"))
    result = refresh_warehouse_availability(
        current_user,
        macrolocal_cluster_id=macrolocal_cluster_id,
        cluster_id=cluster_id,
        force=force,
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@warehouse_slots_api_bp.route("/analytics/warehouse-slots/timeslots", methods=["GET"])
@login_required
def warehouse_slots_timeslots():
    draft_id = _parse_int(request.args.get("draft_id"), "draft_id")
    macrolocal_cluster_id = _parse_int(request.args.get("macrolocal_cluster_id"), "macrolocal_cluster_id")
    cluster_id = _parse_int(request.args.get("cluster_id"), "cluster_id")
    storage_warehouse_id = _parse_int(request.args.get("storage_warehouse_id"), "storage_warehouse_id")

    if None in (draft_id, macrolocal_cluster_id, cluster_id, storage_warehouse_id):
        return jsonify({"ok": False, "error": "Не указаны параметры склада."}), 400

    result = get_warehouse_timeslots(
        current_user,
        draft_id=draft_id,
        macrolocal_cluster_id=macrolocal_cluster_id,
        cluster_id=cluster_id,
        storage_warehouse_id=storage_warehouse_id,
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@warehouse_slots_api_bp.route("/analytics/warehouse-slots/watches", methods=["GET"])
@login_required
def warehouse_slots_watches_list():
    return jsonify({
        "ok": True,
        "watches": list_warehouse_slot_watches(current_user.id),
    })


@warehouse_slots_api_bp.route("/analytics/warehouse-slots/watches", methods=["POST"])
@login_required
def warehouse_slots_watches_add():
    payload = request.get_json(silent=True) or {}
    result = add_warehouse_slot_watch(current_user, payload)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@warehouse_slots_api_bp.route("/analytics/warehouse-slots/watches/<int:watch_id>", methods=["DELETE"])
@login_required
def warehouse_slots_watches_remove(watch_id: int):
    result = remove_warehouse_slot_watch(current_user.id, watch_id)
    status = 200 if result.get("ok") else 404
    return jsonify(result), status
