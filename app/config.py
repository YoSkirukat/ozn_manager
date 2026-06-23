import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"
DEFAULT_DB_PATH = INSTANCE_DIR / "ozn_manager.db"


def _resolve_database_uri() -> str:
    """Всегда возвращает абсолютный путь для SQLite (важно для flask db migrate)."""
    uri = os.environ.get("DATABASE_URL", "").strip()
    if not uri:
        db_path = DEFAULT_DB_PATH
    elif uri.startswith("sqlite:///"):
        raw = uri[len("sqlite:///") :]
        db_path = Path(raw) if Path(raw).is_absolute() else (BASE_DIR / raw)
    else:
        return uri

    db_path = db_path.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Четыре слэша: sqlite:// + /abs/path (Unix)
    return f"sqlite:///{db_path.as_posix()}"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = _resolve_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False, "timeout": 30},
    }
    OZON_CLIENT_ID = os.environ.get("OZON_CLIENT_ID", "")
    OZON_API_KEY = os.environ.get("OZON_API_KEY", "")
    REPORTS_FOLDER = BASE_DIR / "reports"
    APP_VERSION = os.environ.get("APP_VERSION", "1.0.0")
    SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "1") == "1"
    SCHEDULER_TIMEZONE = os.environ.get("SCHEDULER_TIMEZONE", "Europe/Moscow")
    APP_TIMEZONE = os.environ.get("APP_TIMEZONE", SCHEDULER_TIMEZONE)
    SCHEDULER_SYNC_SECONDS = int(os.environ.get("SCHEDULER_SYNC_SECONDS", "30"))
