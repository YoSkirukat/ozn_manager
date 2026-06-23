from flask import current_app

from app.models import ReleaseNote


def get_app_version() -> str:
    """Текущая версия: последний release note или APP_VERSION из конфига."""
    latest = ReleaseNote.query.order_by(ReleaseNote.released_at.desc()).first()
    if latest:
        return latest.version
    return current_app.config.get("APP_VERSION", "1.0.0")
