from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.services.stock_report import (
    get_product_stock_detail,
    get_stock_report_cache,
    get_warehouse_stock_detail,
    load_stock_report,
    save_stock_report_cache,
)

stocks_api_bp = Blueprint("stocks_api", __name__)


@stocks_api_bp.route("/reports/stocks/load", methods=["POST"])
@login_required
def load_stocks():
    result = load_stock_report(current_user)
    if result.get("ok"):
        rows = result.pop("rows", [])
        save_stock_report_cache(current_user.id, rows)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@stocks_api_bp.route("/reports/stocks/warehouse", methods=["GET"])
@login_required
def warehouse_stock():
    warehouse_name = (request.args.get("warehouse_name") or "").strip()
    cached_rows = get_stock_report_cache(current_user.id)
    result = get_warehouse_stock_detail(current_user, warehouse_name, cached_rows)
    status = 200 if result.get("ok") else 404
    return jsonify(result), status


@stocks_api_bp.route("/reports/stocks/product", methods=["GET"])
@login_required
def product_stock():
    product_key = (request.args.get("product_key") or "").strip()
    cached_rows = get_stock_report_cache(current_user.id)
    result = get_product_stock_detail(current_user, product_key, cached_rows)
    status = 200 if result.get("ok") else 404
    return jsonify(result), status
