"""Сервис аудита: запись изменений и вычисление версии сущности."""

from app.extensions import db
from app.models import ChangeLog


def next_version(user_id: int, entity_type: str, entity_id: int) -> int:
    last = (
        ChangeLog.query.filter_by(
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        .order_by(ChangeLog.version.desc())
        .first()
    )
    return (last.version + 1) if last else 1


def log_change(
    user_id: int,
    action_type: str,
    entity_type: str,
    entity_id: int,
    old_value=None,
    new_value=None,
) -> ChangeLog:
    entry = ChangeLog(
        user_id=user_id,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=old_value,
        new_value=new_value,
        version=next_version(user_id, entity_type, entity_id),
    )
    db.session.add(entry)
    return entry
