from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import utcnow
from app.ozon.client import check_seller_credentials
from app.ozon.fbs_stocks import fetch_fbs_warehouses
from app.services.change_log import log_change
from app.services.fbs_stocks import list_fbs_stock_sources, save_fbs_stock_sources

profile_bp = Blueprint("profile", __name__)

FBS_AUTO_WAREHOUSE_VALUE = "auto"


def _load_fbs_warehouses(user) -> tuple[list[dict], str | None]:
    """FBS-склады кабинета и ошибка загрузки (для блока «Внешние данные»)."""
    if not user.has_ozon_credentials():
        return [], None
    try:
        return fetch_fbs_warehouses(user.ozon_client_id, user.ozon_api_key), None
    except Exception as exc:  # noqa: BLE001 — список складов некритичен для профиля
        return [], str(exc)


def _render_profile():
    warehouses, warehouses_error = _load_fbs_warehouses(current_user)
    return render_template(
        "profile/index.html",
        fbs_warehouses=warehouses,
        fbs_warehouses_error=warehouses_error,
        fbs_sources=list_fbs_stock_sources(current_user.id),
        fbs_auto_warehouse_value=FBS_AUTO_WAREHOUSE_VALUE,
    )


def _save_fbs_sources_from_form() -> dict:
    """Собирает настройки остатков FBS из формы профиля и сохраняет их."""
    warehouse_ids = request.form.getlist("fbs_warehouse_id[]")
    warehouse_names = request.form.getlist("fbs_warehouse_name[]")
    stocks_urls = request.form.getlist("fbs_stocks_url[]")

    warehouses, _ = _load_fbs_warehouses(current_user)
    known_names = {
        str(item.get("warehouse_id")): str(item.get("name") or "")
        for item in warehouses
    }

    rows: list[dict] = []
    for index, warehouse_id in enumerate(warehouse_ids):
        warehouse_key = (warehouse_id or "").strip()
        name = known_names.get(warehouse_key)
        if name is None:
            name = warehouse_names[index] if index < len(warehouse_names) else ""
        rows.append(
            {
                "warehouse_id": warehouse_key,
                "warehouse_name": name,
                "stocks_url": stocks_urls[index] if index < len(stocks_urls) else "",
            }
        )
    return save_fbs_stock_sources(current_user, rows)


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

    return _render_profile()


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

    sources_result = _save_fbs_sources_from_form()
    if not sources_result.get("ok"):
        flash(sources_result.get("error") or "Не удалось сохранить склады FBS.", "warning")
        return redirect(url_for("profile.index"))

    current_user.purchase_prices_url = purchase_url or None
    # Одиночная настройка остатков FBS больше не используется: остатки ведутся по складам.
    current_user.fbs_stocks_url = None
    current_user.fbs_warehouse_id = None
    db.session.commit()

    messages = []
    if purchase_url:
        messages.append("ссылка на закупочные цены сохранена")
    else:
        messages.append("ссылка на закупочные цены удалена")

    saved = int(sources_result.get("saved") or 0)
    if saved:
        messages.append(f"складов FBS сохранено: {saved}")
    else:
        messages.append("склады FBS не заданы")

    removed = int(sources_result.get("removed") or 0)
    if removed:
        messages.append(f"удалено складов FBS: {removed}")

    flash("Внешние данные: " + "; ".join(messages) + ".", "success")

    skipped_without_url = int(sources_result.get("skipped_without_url") or 0)
    duplicates = int(sources_result.get("duplicates") or 0)
    warnings = []
    if skipped_without_url:
        warnings.append(
            f"без ссылки на файл остатков пропущено складов: {skipped_without_url}"
        )
    if duplicates:
        warnings.append(f"повторяющихся складов пропущено: {duplicates}")
    if warnings:
        flash("Остатки FBS: " + "; ".join(warnings) + ".", "warning")

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
