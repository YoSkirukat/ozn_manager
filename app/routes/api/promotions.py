from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.services.product_actions import remove_product_from_promotion

promotions_api_bp = Blueprint("promotions_api", __name__)


@promotions_api_bp.route("/analytics/promotions/remove", methods=["POST"])
@login_required
def remove_from_promotion():
    data = request.get_json(silent=True) or {}
    action_id = data.get("action_id")
    product_id = (data.get("product_id") or data.get("ozon_product_id") or "").strip()

    if action_id in (None, ""):
        return jsonify({"ok": False, "error": "Не указана акция."}), 400
    if not product_id:
        return jsonify({"ok": False, "error": "Не указан товар."}), 400

    result = remove_product_from_promotion(current_user, action_id, product_id)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status
