from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.services.dashboard_stats import build_dashboard_stats
from app.services.orders_chart import build_orders_chart, resolve_chart_params

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard/stats")
@login_required
def stats():
    return jsonify(build_dashboard_stats(current_user))


@dashboard_bp.route("/dashboard/orders-chart")
@login_required
def orders_chart():
    date_from, date_to, metric, compare = resolve_chart_params(
        request.args.get("from"),
        request.args.get("to"),
        request.args.get("metric"),
        request.args.get("compare"),
    )
    result = build_orders_chart(current_user.id, date_from, date_to, metric, compare)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status
