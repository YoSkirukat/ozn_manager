from datetime import datetime

from flask import Blueprint, Response, jsonify, request
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.models import Order
from app.services.order_details import get_order_detail
from app.services.order_sync import load_orders_from_ozon
from app.services.orders_export import export_orders_excel
from app.services.orders_filters import (
    _normalize_delivery,
    _normalize_schemes,
    _normalize_statuses,
    _parse_csv_param,
)
from app.services.orders_period import save_orders_period

orders_api_bp = Blueprint("orders_api", __name__)


def _parse_date(value: str):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


@orders_api_bp.route("/orders/load", methods=["POST"])
@login_required
def load_orders():
    data = request.get_json(silent=True) or {}
    date_from = _parse_date(data.get("date_from") or "")
    date_to = _parse_date(data.get("date_to") or "")
    refresh_financials_batch = bool(data.get("refresh_financials_batch"))

    if not date_from or not date_to:
        return jsonify({"ok": False, "error": "Укажите период: дату начала и окончания."}), 400

    result = load_orders_from_ozon(
        current_user,
        date_from,
        date_to,
        refresh_financials_batch=refresh_financials_batch,
    )
    if result.get("ok"):
        save_orders_period(date_from, date_to)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@orders_api_bp.route("/orders/detail", methods=["GET"])
@login_required
def order_detail_lookup():
    """Детали заказа по номеру отправления (предпочтительно) или id."""
    refresh = request.args.get("refresh", "0") == "1"
    posting_number = (request.args.get("posting_number") or "").strip()
    order_id = request.args.get("order_id", type=int)

    if posting_number:
        order = Order.query.filter_by(
            user_id=current_user.id,
            ozon_order_id=posting_number,
        ).first()
    elif order_id:
        order = Order.query.filter_by(id=order_id, user_id=current_user.id).first()
    else:
        return jsonify({"ok": False, "error": "Не указан заказ."}), 400

    if not order:
        return jsonify({"ok": False, "error": "Заказ не найден."}), 404

    result = get_order_detail(current_user, order.id, refresh=refresh)
    status = 200 if result.get("ok") else 404
    return jsonify(result), status


@orders_api_bp.route("/orders/export", methods=["GET"])
@login_required
def export_orders():
    date_from = _parse_date(request.args.get("from"))
    date_to = _parse_date(request.args.get("to"))
    export_type = (request.args.get("type") or "excel").strip().lower()

    if not date_from or not date_to:
        return jsonify({"ok": False, "error": "Укажите период: дату начала и окончания."}), 400

    if export_type not in ("excel", "1c"):
        return jsonify({"ok": False, "error": "Неизвестный тип выгрузки."}), 400

    statuses = _normalize_statuses(_parse_csv_param(request.args.get("status")))
    schemes = _normalize_schemes(_parse_csv_param(request.args.get("scheme")))
    delivery = _normalize_delivery(request.args.get("delivery"))

    content, filename = export_orders_excel(
        current_user,
        date_from,
        date_to,
        export_type=export_type,
        statuses=statuses or None,
        schemes=schemes or None,
        delivery=delivery,
    )
    safe_name = secure_filename(filename) or "orders.xlsx"
    return Response(
        content,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "Cache-Control": "no-store",
        },
    )


@orders_api_bp.route("/orders/<int:order_id>", methods=["GET"])
@login_required
def order_detail(order_id: int):
    refresh = request.args.get("refresh", "0") == "1"
    result = get_order_detail(current_user, order_id, refresh=refresh)
    status = 200 if result.get("ok") else 404
    return jsonify(result), status
