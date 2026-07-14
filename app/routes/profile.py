from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import utcnow
from app.ozon.client import check_seller_credentials
from app.services.change_log import log_change

profile_bp = Blueprint("profile", __name__)


def _ozon_snapshot(user) -> dict:
    return {
        "ozon_client_id": user.ozon_client_id,
        "ozon_api_key_set": bool(user.ozon_api_key),
        "ozon_key_active": user.ozon_key_active,
        "ozon_company_name": user.ozon_company_name,
    }


def _log_ozon_change(user, old_value: dict) -> None:
    log_change(
        user_id=user.id,
        action_type="update",
        entity_type="user",
        entity_id=user.id,
        old_value=old_value,
        new_value=_ozon_snapshot(user),
    )


def _refresh_ozon_status(user, client_id: str, api_key: str) -> dict:
    result = check_seller_credentials(client_id, api_key)
    user.ozon_key_active = result["ok"]
    if result["ok"]:
        user.ozon_company_name = result["company_name"]
    elif not user.ozon_company_name:
        user.ozon_company_name = None
    return result


def _clear_ozon_credentials(user) -> None:
    user.ozon_client_id = None
    user.ozon_api_key = None
    user.ozon_company_name = None
    user.ozon_connected_at = None
    user.ozon_key_active = None


@profile_bp.route("/profile", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        client_id = (request.form.get("ozon_client_id") or "").strip()
        api_key = (request.form.get("ozon_api_key") or "").strip()
        old_value = _ozon_snapshot(current_user)

        current_user.ozon_client_id = client_id or None
        if api_key:
            current_user.ozon_api_key = api_key

        if current_user.has_ozon_credentials():
            check_key = api_key or current_user.ozon_api_key
            result = _refresh_ozon_status(current_user, current_user.ozon_client_id, check_key)
            if result["ok"]:
                current_user.ozon_connected_at = utcnow()
                flash(f"Сохранено. Подключено: {result['company_name']}", "success")
            else:
                current_user.ozon_connected_at = None
                flash(result["error"] or "Ключи сохранены, но проверка не прошла.", "warning")
        else:
            _clear_ozon_credentials(current_user)
            flash("Укажите Client-Id и Api-Key.", "info")

        _log_ozon_change(current_user, old_value)
        db.session.commit()
        return redirect(url_for("profile.index"))

    return render_template("profile/index.html")


@profile_bp.route("/profile/ozon/check", methods=["POST"])
@login_required
def check_ozon():
    if not current_user.has_ozon_credentials():
        flash("Сначала сохраните Client-Id и Api-Key.", "warning")
        return redirect(url_for("profile.index"))

    old_value = _ozon_snapshot(current_user)
    result = _refresh_ozon_status(
        current_user,
        current_user.ozon_client_id,
        current_user.ozon_api_key,
    )

    if result["ok"]:
        if not current_user.ozon_connected_at:
            current_user.ozon_connected_at = utcnow()
        flash(f"Ключ активен. {result['company_name']}", "success")
    else:
        flash(result["error"] or "Ключ неактивен или недоступен.", "warning")

    _log_ozon_change(current_user, old_value)
    db.session.commit()
    return redirect(url_for("profile.index"))


@profile_bp.route("/profile/external", methods=["POST"])
@login_required
def save_external():
    purchase_url = (request.form.get("purchase_prices_url") or "").strip()
    fbs_stocks_url = (request.form.get("fbs_stocks_url") or "").strip()
    current_user.purchase_prices_url = purchase_url or None
    current_user.fbs_stocks_url = fbs_stocks_url or None
    db.session.commit()

    messages = []
    if purchase_url:
        messages.append("ссылка на закупочные цены сохранена")
    else:
        messages.append("ссылка на закупочные цены удалена")
    if fbs_stocks_url:
        messages.append("ссылка «Остатки для FBS» сохранена")
    else:
        messages.append("ссылка «Остатки для FBS» удалена")
    flash("Внешние данные: " + "; ".join(messages) + ".", "success")
    return redirect(url_for("profile.index"))


@profile_bp.route("/profile/ozon/delete", methods=["POST"])
@login_required
def delete_ozon():
    if not current_user.has_ozon_credentials():
        flash("Ключи Ozon не подключены.", "info")
        return redirect(url_for("profile.index"))

    old_value = _ozon_snapshot(current_user)
    _clear_ozon_credentials(current_user)
    _log_ozon_change(current_user, old_value)
    db.session.commit()
    flash("Ключи Ozon удалены.", "success")
    return redirect(url_for("profile.index"))
