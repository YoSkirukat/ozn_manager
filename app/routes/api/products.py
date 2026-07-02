from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Product
from app.services.product_commissions import commission_detail_for_api
from app.services.product_sync import sync_products_from_ozon
from app.services.purchase_prices import _parse_price, apply_purchase_prices_from_content

products_api_bp = Blueprint("products_api", __name__)


@products_api_bp.route("/products/sync", methods=["POST"])
@login_required
def sync_products():
    result = sync_products_from_ozon(current_user)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@products_api_bp.route("/products/purchase-prices/upload", methods=["POST"])
@login_required
def upload_purchase_prices():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "Выберите файл."}), 400

    filename = file.filename.lower()
    if not (filename.endswith(".xls") or filename.endswith(".xlsx")):
        return jsonify({"ok": False, "error": "Поддерживаются только XLS и XLSX."}), 400

    content = file.read()
    if not content:
        return jsonify({"ok": False, "error": "Файл пуст."}), 400

    result = apply_purchase_prices_from_content(current_user, content)
    if result.get("ok"):
        db.session.commit()
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@products_api_bp.route("/products/<int:product_id>/purchase-price", methods=["PATCH"])
@login_required
def update_purchase_price(product_id: int):
    product = Product.query.filter_by(id=product_id, user_id=current_user.id).first()
    if not product:
        return jsonify({"ok": False, "error": "Товар не найден."}), 404

    data = request.get_json(silent=True) or {}
    raw = data.get("purchase_price")

    if raw is None or raw == "":
        product.purchase_price = None
    else:
        price = _parse_price(raw)
        if price is None:
            return jsonify({"ok": False, "error": "Некорректная цена."}), 400
        if price < 0:
            return jsonify({"ok": False, "error": "Цена не может быть отрицательной."}), 400
        product.purchase_price = price

    db.session.commit()

    profit_rows = [
        {"scheme_label": scheme_label, "line": line, "negative": negative}
        for scheme_label, line, negative in product.profit_markup_scheme_rows()
    ]

    return jsonify({
        "ok": True,
        "purchase_price": float(product.purchase_price) if product.purchase_price is not None else None,
        "purchase_price_display": (
            product.purchase_price_display() if product.purchase_price is not None else None
        ),
        "can_show_profit_markup": product.can_show_profit_markup(),
        "profit_rows": profit_rows,
    })


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
