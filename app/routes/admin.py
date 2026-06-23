from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.authz import ROLE_ADMIN, ROLE_USER, admin_required
from app.extensions import db
from datetime import datetime

from app.models import ReleaseNote, User
from app.services.change_log import log_change

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _validate_user_form(*, display_name, username, email, password, role, user_id=None):
    errors = []
    if not display_name:
        errors.append("Укажите имя пользователя.")
    if len(username) < 3:
        errors.append("Логин — минимум 3 символа.")
    if "@" not in email:
        errors.append("Укажите корректный email.")
    if password and len(password) < 6:
        errors.append("Пароль — минимум 6 символов.")
    if role not in (ROLE_ADMIN, ROLE_USER):
        errors.append("Некорректная роль.")

    q = User.query.filter_by(username=username)
    if user_id:
        q = q.filter(User.id != user_id)
    if q.first():
        errors.append("Пользователь с таким логином уже существует.")

    q_email = User.query.filter_by(email=email.lower())
    if user_id:
        q_email = q_email.filter(User.id != user_id)
    if q_email.first():
        errors.append("Email уже используется.")
    return errors


@admin_bp.route("/users", methods=["GET", "POST"])
@login_required
@admin_required
def users():
    if request.method == "POST":
        display_name = (request.form.get("display_name") or "").strip()
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        role = request.form.get("role") or ROLE_USER

        errors = _validate_user_form(
            display_name=display_name,
            username=username,
            email=email,
            password=password,
            role=role,
        )
        if not password:
            errors.append("Укажите пароль для нового пользователя.")

        if errors:
            for msg in errors:
                flash(msg, "danger")
        else:
            user = User(
                display_name=display_name,
                username=username,
                email=email,
                role=role,
                is_active=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            log_change(
                user_id=current_user.id,
                action_type="create",
                entity_type="user",
                entity_id=user.id,
                old_value=None,
                new_value={"username": username, "display_name": display_name, "role": role},
            )
            db.session.commit()
            flash(f"Пользователь «{display_name}» создан.", "success")
            return redirect(url_for("admin.users"))

    users_list = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users_list)


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("Пользователь не найден.", "danger")
        return redirect(url_for("admin.users"))

    if request.method == "POST":
        display_name = (request.form.get("display_name") or "").strip()
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        role = request.form.get("role") or ROLE_USER

        errors = _validate_user_form(
            display_name=display_name,
            username=username,
            email=email,
            password=password,
            role=role,
            user_id=user.id,
        )

        if user.id == current_user.id and role != ROLE_ADMIN:
            errors.append("Нельзя снять с себя роль администратора.")

        if errors:
            for msg in errors:
                flash(msg, "danger")
        else:
            old_value = {
                "display_name": user.display_name,
                "username": user.username,
                "email": user.email,
                "role": user.role,
            }
            user.display_name = display_name
            user.username = username
            user.email = email
            user.role = role
            if password:
                user.set_password(password)
            log_change(
                user_id=current_user.id,
                action_type="update",
                entity_type="user",
                entity_id=user.id,
                old_value=old_value,
                new_value={
                    "display_name": display_name,
                    "username": username,
                    "email": email,
                    "role": role,
                    "password_changed": bool(password),
                },
            )
            db.session.commit()
            flash(f"Пользователь «{display_name}» обновлён.", "success")
            return redirect(url_for("admin.users"))

    return render_template("admin/user_edit.html", user=user)


@admin_bp.route("/users/<int:user_id>/activate", methods=["POST"])
@login_required
@admin_required
def activate_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("Пользователь не найден.", "danger")
        return redirect(url_for("admin.users"))
    if user.is_active:
        flash("Аккаунт уже активирован.", "info")
    else:
        user.is_active = True
        db.session.commit()
        flash(f"Пользователь «{user.display_name or user.username}» активирован.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/deactivate", methods=["POST"])
@login_required
@admin_required
def deactivate_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("Пользователь не найден.", "danger")
        return redirect(url_for("admin.users"))

    if user.id == current_user.id:
        flash("Нельзя заблокировать свой аккаунт.", "danger")
        return redirect(url_for("admin.users"))

    if not user.is_active:
        flash("Аккаунт уже заблокирован.", "info")
        return redirect(url_for("admin.users"))

    if user.is_admin:
        active_admins = User.query.filter_by(role=ROLE_ADMIN, is_active=True).count()
        if active_admins <= 1:
            flash("Нельзя заблокировать единственного активного администратора.", "danger")
            return redirect(url_for("admin.users"))

    user.is_active = False
    db.session.commit()
    flash(f"Пользователь «{user.display_name or user.username}» заблокирован.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("Пользователь не найден.", "danger")
        return redirect(url_for("admin.users"))

    if user.id == current_user.id:
        flash("Нельзя удалить свой аккаунт.", "danger")
        return redirect(url_for("admin.users"))

    if user.is_admin:
        admins_count = User.query.filter_by(role=ROLE_ADMIN).count()
        if admins_count <= 1:
            flash("Нельзя удалить единственного администратора.", "danger")
            return redirect(url_for("admin.users"))

    name = user.display_name or user.username
    db.session.delete(user)
    db.session.commit()
    flash(f"Пользователь «{name}» удалён.", "success")
    return redirect(url_for("admin.users"))


def _parse_release_items(raw: str) -> list[str]:
    return [line.strip() for line in (raw or "").splitlines() if line.strip()]


def _parse_release_date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


@admin_bp.route("/releases", methods=["GET", "POST"])
@login_required
@admin_required
def releases():
    if request.method == "POST":
        version = (request.form.get("version") or "").strip()
        released_at_str = (request.form.get("released_at") or "").strip()
        items_raw = request.form.get("items") or ""
        released_at = _parse_release_date(released_at_str)
        items = _parse_release_items(items_raw)

        errors = []
        if not version:
            errors.append("Укажите номер версии.")
        if not released_at:
            errors.append("Укажите дату в формате ГГГГ-ММ-ДД.")
        if not items:
            errors.append("Добавьте хотя бы один пункт изменений.")
        if ReleaseNote.query.filter_by(version=version).first():
            errors.append("Версия с таким номером уже существует.")

        if errors:
            for msg in errors:
                flash(msg, "danger")
        else:
            note = ReleaseNote(version=version, released_at=released_at, items=items)
            db.session.add(note)
            db.session.commit()
            flash(f"Версия {version} опубликована.", "success")
            return redirect(url_for("admin.releases"))

    releases_list = ReleaseNote.query.order_by(ReleaseNote.released_at.desc()).all()
    return render_template("admin/releases.html", releases=releases_list)


@admin_bp.route("/releases/<int:note_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_release(note_id):
    note = db.session.get(ReleaseNote, note_id)
    if not note:
        flash("Запись не найдена.", "danger")
        return redirect(url_for("admin.releases"))

    if request.method == "POST":
        version = (request.form.get("version") or "").strip()
        released_at_str = (request.form.get("released_at") or "").strip()
        items_raw = request.form.get("items") or ""
        released_at = _parse_release_date(released_at_str)
        items = _parse_release_items(items_raw)

        errors = []
        if not version:
            errors.append("Укажите номер версии.")
        if not released_at:
            errors.append("Укажите дату в формате ГГГГ-ММ-ДД.")
        if not items:
            errors.append("Добавьте хотя бы один пункт изменений.")
        existing = ReleaseNote.query.filter_by(version=version).first()
        if existing and existing.id != note.id:
            errors.append("Версия с таким номером уже существует.")

        if errors:
            for msg in errors:
                flash(msg, "danger")
        else:
            note.version = version
            note.released_at = released_at
            note.items = items
            db.session.commit()
            flash(f"Версия {version} обновлена.", "success")
            return redirect(url_for("main.changelog"))

    items_text = "\n".join(note.items_list)
    return render_template("admin/release_edit.html", note=note, items_text=items_text)


@admin_bp.route("/releases/<int:note_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_release(note_id):
    note = db.session.get(ReleaseNote, note_id)
    if note:
        db.session.delete(note)
        db.session.commit()
        flash("Версия удалена.", "success")
    return redirect(url_for("admin.releases"))
