"""Повторные попытки записи в SQLite при database is locked."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import OperationalError

from app.extensions import db

T = TypeVar("T")

DEFAULT_RETRIES = 12
DEFAULT_DELAY = 0.3
# Записи из веб-интерфейса: короткие блокировки (синхронизация с Ozon) пережидаем
# молча, но не держим запрос пользователя минутами.
DEFAULT_WEB_RETRIES = 4
DEFAULT_WEB_DELAY = 0.3
LOCKED_DB_MESSAGE = (
    "База данных занята: идёт синхронизация данных с Ozon. "
    "Изменения не сохранены — повторите действие через минуту."
)
_WRITE_LOCK = threading.RLock()


def is_sqlite_locked_error(exc: BaseException) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    orig = getattr(exc, "orig", None)
    if orig is not None and getattr(orig, "sqlite_errorname", None) == "SQLITE_BUSY":
        return True
    return "database is locked" in str(exc).lower()


def db_session_commit(*, retries: int = DEFAULT_RETRIES, delay: float = DEFAULT_DELAY) -> None:
    """commit() с повторами при блокировке SQLite (записи сериализуются)."""
    with _WRITE_LOCK:
        last_error: OperationalError | None = None
        for attempt in range(retries):
            try:
                db.session.commit()
                return
            except OperationalError as exc:
                db.session.rollback()
                if not is_sqlite_locked_error(exc):
                    raise
                last_error = exc
                if attempt < retries - 1:
                    time.sleep(delay * (attempt + 1))
        if last_error is not None:
            raise last_error


def db_session_run(
    fn: Callable[[], T],
    *,
    retries: int = DEFAULT_RETRIES,
    delay: float = DEFAULT_DELAY,
) -> T:
    """Выполнить fn(); при database is locked — rollback и повтор."""
    with _WRITE_LOCK:
        last_error: OperationalError | None = None
        for attempt in range(retries):
            try:
                return fn()
            except OperationalError as exc:
                db.session.rollback()
                if not is_sqlite_locked_error(exc):
                    raise
                last_error = exc
                if attempt < retries - 1:
                    time.sleep(delay * (attempt + 1))
        if last_error is not None:
            raise last_error
    raise RuntimeError("db_session_run failed without error")


def db_write_with_retry(
    fn: Callable[[], T],
    *,
    retries: int = DEFAULT_WEB_RETRIES,
    delay: float = DEFAULT_WEB_DELAY,
) -> tuple[bool, T | None]:
    """Запись из веб-интерфейса с повторами при блокировке SQLite.

    Возвращает (True, результат) при успехе и (False, None), если база так и
    осталась занятой: вызывающий код показывает пользователю LOCKED_DB_MESSAGE
    вместо страницы 500. fn() должна быть идемпотентной — при повторе она
    вызывается заново после rollback().
    """
    try:
        return True, db_session_run(fn, retries=retries, delay=delay)
    except OperationalError as exc:
        db.session.rollback()
        if not is_sqlite_locked_error(exc):
            raise
        return False, None
