from pathlib import Path

from flask import Flask

from app.config import Config
from app.extensions import db, login_manager, migrate


def create_app(config_class=Config):
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder="../templates",
        static_folder="../static",
    )
    app.config.from_object(config_class)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["REPORTS_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import redirect, request, url_for
        return redirect(url_for("auth.login", next=request.path))

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.api import api_bp
    from app.routes.admin import admin_bp
    from app.routes.profile import profile_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(profile_bp)

    from app.datetime_fmt import format_date, format_datetime
    from app.money_fmt import format_money_display_text, format_money_ru

    @app.template_filter("dt")
    def jinja_format_datetime(value, fmt="%d.%m.%Y %H:%M"):
        return format_datetime(value, fmt)

    @app.template_filter("d")
    def jinja_format_date(value, fmt="%d.%m.%Y"):
        return format_date(value, fmt)

    @app.template_filter("money")
    def jinja_format_money(value, decimals=2):
        return format_money_ru(value, decimals=int(decimals))

    @app.template_filter("money_text")
    def jinja_format_money_text(value):
        return format_money_display_text(value)

    @app.context_processor
    def inject_globals():
        from app.authz import is_admin
        from app.version import get_app_version
        return {
            "is_admin": is_admin(),
            "app_version": get_app_version(),
            "app_timezone": app.config.get("APP_TIMEZONE", "Europe/Moscow"),
        }

    from app.scheduled_tasks.scheduler import init_scheduler

    init_scheduler(app)

    @app.route("/favicon.ico")
    def favicon():
        from flask import send_from_directory

        return send_from_directory(
            Path(app.root_path).parent,
            "favicon.ico",
            mimetype="image/x-icon",
        )

    @app.before_request
    def require_active_account():
        from flask import flash, redirect, request, url_for
        from flask_login import current_user, logout_user

        if not current_user.is_authenticated:
            return
        if request.endpoint and request.endpoint.startswith("auth."):
            return
        if not current_user.is_active:
            logout_user()
            flash("Аккаунт не активирован. Обратитесь к администратору.", "warning")
            return redirect(url_for("auth.login"))

    return app
