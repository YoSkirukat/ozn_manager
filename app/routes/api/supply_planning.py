from flask import Blueprint, Response, jsonify, request
from flask_login import login_required

from app.services.supply_planning_export import (
    build_supply_planning_export_filename,
    build_supply_planning_ozon_xls,
    build_supply_planning_send_xls,
    content_disposition_attachment,
)

supply_planning_api_bp = Blueprint("supply_planning_api", __name__)


@supply_planning_api_bp.route("/analytics/supply-planning/export", methods=["POST"])
@login_required
def export_supply_planning_send():
    payload = request.get_json(silent=True) or {}
    export_type = str(payload.get("type") or "1c").strip().lower()
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return jsonify({"ok": False, "error": "Не передан список товаров."}), 400

    warehouse_name = str(payload.get("warehouse") or "").strip()

    if export_type == "ozon":
        rows: list[tuple[str, str, int]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            offer_id = str(item.get("offer_id") or "").strip()
            try:
                quantity = int(item.get("quantity") or 0)
            except (TypeError, ValueError):
                continue
            if not offer_id or offer_id == "—" or quantity <= 0:
                continue
            name = str(item.get("name") or "").strip()
            rows.append((offer_id, name, quantity))

        if not rows:
            return jsonify({
                "ok": False,
                "error": "Укажите количество в колонке «Отправить» хотя бы для одного товара.",
            }), 400

        content = build_supply_planning_ozon_xls(rows)
    else:
        rows: list[tuple[str, int]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            barcode = str(item.get("barcode") or "").strip()
            try:
                quantity = int(item.get("quantity") or 0)
            except (TypeError, ValueError):
                continue
            if not barcode or barcode == "—" or quantity <= 0:
                continue
            rows.append((barcode, quantity))

        if not rows:
            return jsonify({
                "ok": False,
                "error": "Укажите количество в колонке «Отправить» хотя бы для одного товара.",
            }), 400

        content = build_supply_planning_send_xls(rows)

    filename = build_supply_planning_export_filename(warehouse_name)
    return Response(
        content,
        mimetype="application/vnd.ms-excel",
        headers={
            "Content-Disposition": content_disposition_attachment(filename),
            "Cache-Control": "no-store",
        },
    )
