from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.services.price_experiments import (
    add_products_to_experiment,
    create_experiment,
    delete_experiment,
    get_experiment,
    list_experiments,
    remove_item,
    search_products_for_experiment,
    set_experiment_running,
    take_daily_snapshots,
    update_experiment,
    update_item_comment,
)

price_experiments_api_bp = Blueprint("price_experiments_api", __name__)


def _parse_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@price_experiments_api_bp.route("/analytics/price-experiments", methods=["GET"])
@login_required
def experiments_list():
    return jsonify({"ok": True, "experiments": list_experiments(current_user.id)})


@price_experiments_api_bp.route("/analytics/price-experiments", methods=["POST"])
@login_required
def experiments_create():
    payload = request.get_json(silent=True) or {}
    result = create_experiment(
        current_user.id,
        title=str(payload.get("title") or ""),
        note=str(payload.get("note") or ""),
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@price_experiments_api_bp.route("/analytics/price-experiments/<int:experiment_id>", methods=["GET"])
@login_required
def experiments_detail(experiment_id: int):
    experiment = get_experiment(current_user.id, experiment_id)
    if not experiment:
        return jsonify({"ok": False, "error": "Эксперимент не найден."}), 404
    return jsonify({"ok": True, "experiment": experiment})


@price_experiments_api_bp.route("/analytics/price-experiments/<int:experiment_id>", methods=["PATCH"])
@login_required
def experiments_update(experiment_id: int):
    payload = request.get_json(silent=True) or {}
    if "running" in payload:
        result = set_experiment_running(
            current_user.id,
            experiment_id,
            running=bool(payload.get("running")),
        )
        status = 200 if result.get("ok") else 400
        return jsonify(result), status

    result = update_experiment(
        current_user.id,
        experiment_id,
        title=str(payload.get("title") or ""),
        note=str(payload.get("note") or ""),
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@price_experiments_api_bp.route("/analytics/price-experiments/<int:experiment_id>", methods=["DELETE"])
@login_required
def experiments_delete(experiment_id: int):
    result = delete_experiment(current_user.id, experiment_id)
    status = 200 if result.get("ok") else 404
    return jsonify(result), status


@price_experiments_api_bp.route(
    "/analytics/price-experiments/<int:experiment_id>/products",
    methods=["POST"],
)
@login_required
def experiments_add_product(experiment_id: int):
    payload = request.get_json(silent=True) or {}
    product_ids = payload.get("product_ids")
    if not isinstance(product_ids, list):
        single_id = _parse_int(payload.get("product_id"))
        product_ids = [single_id] if single_id else []
    product_ids = [pid for pid in (_parse_int(v) for v in product_ids) if pid]
    if not product_ids:
        return jsonify({"ok": False, "error": "Не выбран ни один товар."}), 400
    result = add_products_to_experiment(
        current_user,
        experiment_id,
        product_ids,
        comment=str(payload.get("comment") or ""),
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@price_experiments_api_bp.route("/analytics/price-experiments/products/search", methods=["GET"])
@login_required
def experiments_search_products():
    query = request.args.get("q") or ""
    items = search_products_for_experiment(current_user.id, query)
    return jsonify({"ok": True, "products": items})


@price_experiments_api_bp.route("/analytics/price-experiments/items/<int:item_id>", methods=["PATCH"])
@login_required
def experiments_update_item(item_id: int):
    payload = request.get_json(silent=True) or {}
    result = update_item_comment(current_user.id, item_id, str(payload.get("comment") or ""))
    status = 200 if result.get("ok") else 404
    return jsonify(result), status


@price_experiments_api_bp.route("/analytics/price-experiments/items/<int:item_id>", methods=["DELETE"])
@login_required
def experiments_remove_item(item_id: int):
    result = remove_item(current_user.id, item_id)
    status = 200 if result.get("ok") else 404
    return jsonify(result), status


@price_experiments_api_bp.route("/analytics/price-experiments/snapshot", methods=["POST"])
@login_required
def experiments_snapshot_now():
    payload = request.get_json(silent=True) or {}
    experiment_id = _parse_int(payload.get("experiment_id"))
    result = take_daily_snapshots(current_user, experiment_id=experiment_id)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status
