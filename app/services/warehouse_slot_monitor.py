"""Мониторинг доступности складов FBO для уведомлений."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from flask import current_app

from app.db_sqlite import db_session_commit
from app.extensions import db
from app.models import WarehouseSlotWatch
from app.services.warehouse_slots import (
    REFRESH_CACHE_DIR,
    _refresh_single_cluster,
)

logger = logging.getLogger(__name__)

MONITOR_CLUSTER_DEBOUNCE_SEC = 300
STATE_FULL_AVAILABLE = "FULL_AVAILABLE"


def list_warehouse_slot_watches(user_id: int) -> list[dict]:
    rows = (
        WarehouseSlotWatch.query.filter_by(user_id=user_id)
        .order_by(WarehouseSlotWatch.cluster_name.asc(), WarehouseSlotWatch.warehouse_name.asc())
        .all()
    )
    return [row.to_dict() for row in rows]


def user_has_warehouse_slot_watches(user_id: int) -> bool:
    return (
        WarehouseSlotWatch.query.filter_by(user_id=user_id)
        .with_entities(WarehouseSlotWatch.id)
        .first()
        is not None
    )


def add_warehouse_slot_watch(user, payload: dict) -> dict:
    macrolocal_cluster_id = payload.get("macrolocal_cluster_id")
    cluster_id = payload.get("cluster_id")
    storage_warehouse_id = payload.get("storage_warehouse_id")
    warehouse_name = str(payload.get("warehouse_name") or "—").strip() or "—"
    cluster_name = str(payload.get("cluster_name") or "—").strip() or "—"

    try:
        macrolocal_cluster_id = int(macrolocal_cluster_id)
        cluster_id = int(cluster_id)
        storage_warehouse_id = int(storage_warehouse_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Некорректные параметры склада."}

    if not macrolocal_cluster_id or not storage_warehouse_id:
        return {"ok": False, "error": "Не указан склад для мониторинга."}

    watch = WarehouseSlotWatch.query.filter_by(
        user_id=user.id,
        macrolocal_cluster_id=macrolocal_cluster_id,
        storage_warehouse_id=storage_warehouse_id,
    ).first()
    if watch:
        watch.warehouse_name = warehouse_name
        watch.cluster_name = cluster_name
        watch.cluster_id = cluster_id
        watch.last_availability_state = None
        db_session_commit()
        return {"ok": True, "watch": watch.to_dict(), "created": False}

    watch = WarehouseSlotWatch(
        user_id=user.id,
        macrolocal_cluster_id=macrolocal_cluster_id,
        cluster_id=cluster_id,
        storage_warehouse_id=storage_warehouse_id,
        warehouse_name=warehouse_name,
        cluster_name=cluster_name,
        last_availability_state=None,
    )
    db.session.add(watch)
    db_session_commit()
    return {"ok": True, "watch": watch.to_dict(), "created": True}


def remove_warehouse_slot_watch(user_id: int, watch_id: int) -> dict:
    watch = WarehouseSlotWatch.query.filter_by(user_id=user_id, id=watch_id).first()
    if not watch:
        return {"ok": False, "error": "Склад не найден в списке мониторинга."}
    db.session.delete(watch)
    db_session_commit()
    return {"ok": True}


def _monitor_debounce_path(user_id: int, macrolocal_cluster_id: int) -> Path:
    base = Path(current_app.instance_path) / REFRESH_CACHE_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / f"monitor_{user_id}_{macrolocal_cluster_id}.ts"


def _monitor_debounce_active(user_id: int, macrolocal_cluster_id: int) -> bool:
    path = _monitor_debounce_path(user_id, macrolocal_cluster_id)
    if not path.is_file():
        return False
    try:
        saved_at = float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return time.time() - saved_at < MONITOR_CLUSTER_DEBOUNCE_SEC


def _touch_monitor_debounce(user_id: int, macrolocal_cluster_id: int) -> None:
    path = _monitor_debounce_path(user_id, macrolocal_cluster_id)
    path.write_text(str(time.time()), encoding="utf-8")


def _warehouse_state_map(warehouses: list[dict]) -> dict[tuple[int, int], dict]:
    mapping: dict[tuple[int, int], dict] = {}
    for row in warehouses:
        macrolocal_id = int(row.get("macrolocal_cluster_id") or 0)
        warehouse_id = int(row.get("storage_warehouse_id") or 0)
        if macrolocal_id and warehouse_id:
            mapping[(macrolocal_id, warehouse_id)] = row
    return mapping


def check_warehouse_slot_watches(user) -> None:
    if not user.has_ozon_credentials():
        return

    watches = WarehouseSlotWatch.query.filter_by(user_id=user.id).all()
    if not watches:
        return

    clusters: dict[int, list[WarehouseSlotWatch]] = {}
    for watch in watches:
        clusters.setdefault(int(watch.macrolocal_cluster_id), []).append(watch)

    for macrolocal_cluster_id, cluster_watches in clusters.items():
        if _monitor_debounce_active(user.id, macrolocal_cluster_id):
            continue

        cluster_id = int(cluster_watches[0].cluster_id or 0)
        result = _refresh_single_cluster(
            user,
            macrolocal_cluster_id=macrolocal_cluster_id,
            cluster_id=cluster_id or None,
            force=True,
        )
        _touch_monitor_debounce(user.id, macrolocal_cluster_id)

        if not result.get("ok"):
            logger.debug(
                "Warehouse slot monitor failed for user %s cluster %s: %s",
                user.id,
                macrolocal_cluster_id,
                result.get("error"),
            )
            continue

        state_map = _warehouse_state_map(result.get("warehouses") or [])
        for watch in cluster_watches:
            row = state_map.get((macrolocal_cluster_id, int(watch.storage_warehouse_id)))
            if not row:
                continue

            new_state = str(row.get("availability_state") or "")
            old_state = str(watch.last_availability_state or "")
            if new_state == STATE_FULL_AVAILABLE and old_state != STATE_FULL_AVAILABLE:
                from app.services.notifications_service import notify_warehouse_slot_available

                notify_warehouse_slot_available(user, watch, row)

            if new_state:
                watch.last_availability_state = new_state
                watch.warehouse_name = str(row.get("name") or watch.warehouse_name)
                watch.cluster_name = str(row.get("cluster_name") or watch.cluster_name)

    try:
        db_session_commit()
    except Exception:
        logger.exception("Warehouse slot monitor commit failed for user %s", user.id)
        db.session.rollback()
