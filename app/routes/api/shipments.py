from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.models import Shipment
from app.services.supply_details import get_supply_detail
from app.services.supply_items import refresh_shipments_totals_batch
from app.services.supply_sync import load_supplies_from_ozon

shipments_api_bp = Blueprint("shipments_api", __name__)


def _parse_date(value: str):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


@shipments_api_bp.route("/shipments/load", methods=["POST"])
@login_required
def load_shipments():
    data = request.get_json(silent=True) or {}
    date_from = _parse_date(data.get("date_from") or "")
    date_to = _parse_date(data.get("date_to") or "")

    if not date_from or not date_to:
        return jsonify({"ok": False, "error": "Укажите период: дату начала и окончания."}), 400

    result = load_supplies_from_ozon(current_user, date_from, date_to)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@shipments_api_bp.route("/shipments/detail", methods=["GET"])
@login_required
def shipment_detail():
    shipment_id = request.args.get("shipment_id", type=int)
    if not shipment_id:
        return jsonify({"ok": False, "error": "Не указана поставка."}), 400

    result = get_supply_detail(current_user, shipment_id)
    status = 200 if result.get("ok") else 404
    return jsonify(result), status


@shipments_api_bp.route("/shipments/refresh-totals", methods=["POST"])
@login_required
def refresh_shipment_totals():
    data = request.get_json(silent=True) or {}
    raw_ids = data.get("shipment_ids") or []
    shipment_ids: list[int] = []
    for value in raw_ids:
        try:
            shipment_ids.append(int(value))
        except (TypeError, ValueError):
            continue

    if not shipment_ids:
        return jsonify({"ok": True, "updates": [], "has_more": False})

    shipments = Shipment.query.filter(
        Shipment.user_id == current_user.id,
        Shipment.id.in_(shipment_ids),
    ).all()

    updates, has_more = refresh_shipments_totals_batch(
        current_user,
        shipments,
        shipment_ids=shipment_ids,
        max_items=25,
    )

    return jsonify({"ok": True, "updates": updates, "has_more": has_more})
