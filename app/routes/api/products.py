from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.models import Product
from app.services.product_commissions import commission_detail_for_api
from app.services.product_sync import sync_products_from_ozon

products_api_bp = Blueprint("products_api", __name__)


@products_api_bp.route("/products/sync", methods=["POST"])
@login_required
def sync_products():
    result = sync_products_from_ozon(current_user)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@products_api_bp.route("/products/<int:product_id>/commission", methods=["GET"])
@login_required
def product_commission_detail(product_id: int):
    scheme = (request.args.get("scheme") or "").strip().lower()
    if scheme not in ("fbo", "fbs"):
        return jsonify({"ok": False, "error": "Укажите схему: fbo или fbs."}), 400

    product = Product.query.filter_by(id=product_id, user_id=current_user.id).first()
    if not product:
        return jsonify({"ok": False, "error": "Товар не найден."}), 404

    sale_price_override = request.args.get("sale_price")
    if sale_price_override not in (None, ""):
        try:
            sale_price = float(sale_price_override)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Некорректная цена продажи."}), 400
    else:
        sale_price = product.effective_sale_price()
    block = commission_detail_for_api(product.commission_details, scheme, sale_price=sale_price)
    if not block:
        return jsonify({
            "ok": False,
            "error": "Нет данных о комиссии. Выполните синхронизацию товаров из Ozon.",
        }), 404

    scheme_label = "FBO" if scheme == "fbo" else "FBS"
    return jsonify({
        "ok": True,
        "scheme": scheme,
        "scheme_label": scheme_label,
        "header": {
            "offer_id": product.offer_id or "—",
            "name": product.name,
            "price": sale_price,
            "base_price": float(product.price) if product.price is not None else 0,
            "is_promotional_price": product.uses_promotional_sale_price(),
        },
        "total": block.get("total"),
        "total_min": block.get("total_min"),
        "total_max": block.get("total_max"),
        "total_display": block.get("total_display"),
        "rows": block.get("rows") or [],
    })
