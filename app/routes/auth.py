from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.models import User

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated and current_user.is_active:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if not user.is_active:
                flash(
                    "Аккаунт ожидает активации администратором. "
                    "После одобрения вы сможете войти.",
                    "warning",
                )
            else:
                login_user(user, remember=bool(request.form.get("remember")))
                next_url = request.args.get("next") or url_for("main.index")
                return redirect(next_url)
        else:
            flash("Неверный логин или пароль.", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated and current_user.is_active:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""

        errors = []
        if len(username) < 3:
            errors.append("Имя пользователя — минимум 3 символа.")
        if "@" not in email:
            errors.append("Укажите корректный email.")
        if len(password) < 6:
            errors.append("Пароль — минимум 6 символов.")
        if password != password2:
            errors.append("Пароли не совпадают.")
        if User.query.filter_by(username=username).first():
            errors.append("Такой пользователь уже существует.")
        if User.query.filter_by(email=email).first():
            errors.append("Email уже зарегистрирован.")

        if errors:
            for msg in errors:
                flash(msg, "danger")
        else:
            user = User(
                username=username,
                email=email,
                display_name=username,
                role=User.ROLE_USER,
                is_active=False,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash(
                "Регистрация принята. Администратор активирует аккаунт — "
                "после этого вы сможете войти.",
                "success",
            )
            return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Вы вышли из системы.", "info")
    return redirect(url_for("auth.login"))
