"""Страница «Склады и слоты»: доступные склады FBO и таймслоты."""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from flask import current_app

from app.models import Product
from app.ozon.warehouse_slots import (
    create_direct_draft,
    default_timeslot_period,
    fetch_cluster_list,
    fetch_draft_timeslots,
    friendly_ozon_error,
    wait_for_draft_info,
)

CLUSTER_LIST_CACHE_SEC = 3600
REFRESH_DEBOUNCE_SEC = 45
TIMESLOT_CACHE_SEC = 300
REFRESH_CACHE_DIR = "warehouse_slots_cache"

AVAILABILITY_LABELS = {
    "FULL_AVAILABLE": "Доступен",
    "PARTIAL_AVAILABLE": "Частично доступен",
    "NOT_AVAILABLE": "Недоступен",
    "UNSPECIFIED": "—",
}

INVALID_REASON_LABELS = {
    "UNSPECIFIED": "",
    "NOT_AVAILABLE_RANK": "Низкий рейтинг",
    "NOT_AVAILABLE_MATRIX": "Недоступен по матрице",
    "NOT_AVAILABLE_ROUTE": "Нет маршрута",
    "NOT_AVAILABLE_CAPACITY": "Нет ёмкости",
}


def _cache_dir() -> Path:
    base = Path(current_app.instance_path) / REFRESH_CACHE_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base


def _refresh_cache_path(user_id: int, macrolocal_cluster_id: int) -> Path:
    return _cache_dir() / f"refresh_{user_id}_{macrolocal_cluster_id}.json"


def _refresh_cache_path_all(user_id: int) -> Path:
    return _cache_dir() / f"refresh_{user_id}_all.json"


def _timeslot_cache_path(user_id: int, draft_id: int, storage_warehouse_id: int) -> Path:
    return _cache_dir() / f"timeslots_{user_id}_{draft_id}_{storage_warehouse_id}.json"


def _read_json_cache(path: Path, ttl_sec: int) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        saved_at = float(payload.get("saved_at") or 0)
        if time.time() - saved_at > ttl_sec:
            return None
        data = payload.get("data")
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _write_json_cache(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps({"saved_at": time.time(), "data": data}, ensure_ascii=False),
        encoding="utf-8",
    )


def _cluster_list_cache_path(user_id: int) -> Path:
    return _cache_dir() / f"cluster_list_{user_id}.json"


def _get_cluster_list_cached(user) -> list[dict]:
    path = _cluster_list_cache_path(user.id)
    cached = _read_json_cache(path, CLUSTER_LIST_CACHE_SEC)
    if cached:
        clusters = cached.get("clusters")
        if isinstance(clusters, list) and clusters:
            return clusters

    clusters = fetch_cluster_list(user.ozon_client_id, user.ozon_api_key)
    _write_json_cache(path, {"clusters": clusters})
    return clusters


def _sample_sku(user_id: int) -> int | None:
    product = (
        Product.query.filter_by(user_id=user_id)
        .filter(Product.sku.isnot(None))
        .filter(Product.sku != "")
        .order_by(Product.id.asc())
        .first()
    )
    if not product or not product.sku:
        return None
    try:
        return int(str(product.sku).strip())
    except (TypeError, ValueError):
        return None


def _availability_label(state: str | None) -> str:
    return AVAILABILITY_LABELS.get(str(state or "").strip(), str(state or "—"))


def _invalid_reason_label(reason: str | None) -> str:
    return INVALID_REASON_LABELS.get(str(reason or "").strip(), str(reason or "").strip())


def _macrolocal_cluster_options(clusters: list[dict]) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen: set[int] = set()
    for cluster in clusters:
        macrolocal_id = cluster.get("macrolocal_cluster_id")
        if macrolocal_id is None:
            continue
        macrolocal_id = int(macrolocal_id)
        if macrolocal_id in seen:
            continue
        seen.add(macrolocal_id)
        options.append(
            {
                "macrolocal_cluster_id": macrolocal_id,
                "cluster_id": int(cluster.get("id") or 0),
                "name": str(cluster.get("name") or f"Кластер {macrolocal_id}"),
            }
        )
    options.sort(key=lambda item: item["name"].lower())
    return options


def list_macrolocal_clusters(user) -> dict:
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле."}

    try:
        clusters = _get_cluster_list_cached(user)
    except RuntimeError as exc:
        return {"ok": False, "error": friendly_ozon_error(exc)}

    options = _macrolocal_cluster_options(clusters)
    return {"ok": True, "clusters": options}


def _pick_reference_warehouse(clusters: list[dict], macrolocal_cluster_id: int) -> dict | None:
    for cluster in clusters:
        if int(cluster.get("macrolocal_cluster_id") or 0) != int(macrolocal_cluster_id):
            continue
        cluster_id = int(cluster.get("id") or 0)
        for logistic in cluster.get("logistic_clusters") or []:
            if not isinstance(logistic, dict):
                continue
            for warehouse in logistic.get("warehouses") or []:
                if not isinstance(warehouse, dict):
                    continue
                warehouse_id = warehouse.get("warehouse_id")
                if warehouse_id is None:
                    continue
                return {
                    "macrolocal_cluster_id": macrolocal_cluster_id,
                    "cluster_id": cluster_id,
                    "storage_warehouse_id": int(warehouse_id),
                    "storage_warehouse_name": str(warehouse.get("name") or "—"),
                    "cluster_name": str(cluster.get("name") or "—"),
                }
    return None


def _normalize_draft_warehouses(
    info: dict,
    *,
    draft_id: int,
    cluster_id: int,
) -> list[dict]:
    rows: list[dict] = []
    for cluster in info.get("clusters") or []:
        if not isinstance(cluster, dict):
            continue
        cluster_name = str(cluster.get("cluster_name") or "—")
        macrolocal_cluster_id = int(cluster.get("macrolocal_cluster_id") or 0)
        for warehouse in cluster.get("warehouses") or []:
            if not isinstance(warehouse, dict):
                continue
            storage = warehouse.get("storage_warehouse")
            if not isinstance(storage, dict):
                continue
            availability = warehouse.get("availability_status")
            if not isinstance(availability, dict):
                availability = {}
            state = str(availability.get("state") or "UNSPECIFIED")
            invalid_reason = str(availability.get("invalid_reason") or "UNSPECIFIED")
            rows.append(
                {
                    "macrolocal_cluster_id": macrolocal_cluster_id,
                    "cluster_id": int(cluster_id),
                    "cluster_name": cluster_name,
                    "draft_id": int(draft_id),
                    "storage_warehouse_id": int(storage.get("warehouse_id") or 0),
                    "name": str(storage.get("name") or "—"),
                    "address": str(storage.get("address") or "—"),
                    "availability_state": state,
                    "availability_label": _availability_label(state),
                    "invalid_reason": invalid_reason,
                    "invalid_reason_label": _invalid_reason_label(invalid_reason),
                    "total_rank": warehouse.get("total_rank"),
                    "total_score": warehouse.get("total_score"),
                    "is_available": state == "FULL_AVAILABLE",
                }
            )

    rows.sort(
        key=lambda row: (
            0 if row["is_available"] else 1,
            row.get("total_rank") if row.get("total_rank") is not None else 9999,
            row["name"].lower(),
        )
    )
    return rows


def _refresh_single_cluster(
    user,
    *,
    macrolocal_cluster_id: int,
    cluster_id: int | None = None,
    force: bool = False,
) -> dict:
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле."}

    cache_path = _refresh_cache_path(user.id, macrolocal_cluster_id)
    if not force:
        cached = _read_json_cache(cache_path, REFRESH_DEBOUNCE_SEC)
        if cached:
            cached = dict(cached)
            cached["ok"] = True
            cached["cached"] = True
            return cached

    sku = _sample_sku(user.id)
    if sku is None:
        return {
            "ok": False,
            "error": "Синхронизируйте товары из Ozon — для проверки складов нужен SKU.",
        }

    try:
        clusters = _get_cluster_list_cached(user)
    except RuntimeError as exc:
        return {"ok": False, "error": friendly_ozon_error(exc)}

    reference = _pick_reference_warehouse(clusters, macrolocal_cluster_id)
    if not reference:
        return {"ok": False, "error": "Не удалось найти склады выбранного кластера."}

    if cluster_id:
        reference["cluster_id"] = int(cluster_id)

    try:
        draft_id = create_direct_draft(
            user.ozon_client_id,
            user.ozon_api_key,
            sku=sku,
            macrolocal_cluster_id=reference["macrolocal_cluster_id"],
            cluster_id=reference["cluster_id"],
            storage_warehouse_id=reference["storage_warehouse_id"],
        )
        info = wait_for_draft_info(user.ozon_client_id, user.ozon_api_key, draft_id)
    except RuntimeError as exc:
        return {"ok": False, "error": friendly_ozon_error(exc)}

    warehouses = _normalize_draft_warehouses(
        info,
        draft_id=draft_id,
        cluster_id=reference["cluster_id"],
    )
    if not warehouses:
        return {"ok": False, "error": "Ozon не вернул список складов для выбранного кластера."}

    result = {
        "ok": True,
        "cached": False,
        "all_clusters": False,
        "draft_id": draft_id,
        "sku": sku,
        "cluster_name": reference["cluster_name"],
        "macrolocal_cluster_id": reference["macrolocal_cluster_id"],
        "cluster_id": reference["cluster_id"],
        "warehouses": warehouses,
        "summary": {
            "total": len(warehouses),
            "available": sum(1 for row in warehouses if row["is_available"]),
        },
    }
    _write_json_cache(cache_path, result)
    return result


def refresh_warehouse_availability(
    user,
    *,
    macrolocal_cluster_id: int | None,
    cluster_id: int | None = None,
    force: bool = False,
) -> dict:
    if macrolocal_cluster_id is not None:
        return _refresh_single_cluster(
            user,
            macrolocal_cluster_id=macrolocal_cluster_id,
            cluster_id=cluster_id,
            force=force,
        )

    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле."}

    cache_path = _refresh_cache_path_all(user.id)
    if not force:
        cached = _read_json_cache(cache_path, REFRESH_DEBOUNCE_SEC)
        if cached:
            cached = dict(cached)
            cached["ok"] = True
            cached["cached"] = True
            return cached

    try:
        clusters = _get_cluster_list_cached(user)
    except RuntimeError as exc:
        return {"ok": False, "error": friendly_ozon_error(exc)}

    options = _macrolocal_cluster_options(clusters)
    if not options:
        return {"ok": False, "error": "Не удалось получить список кластеров Ozon."}

    all_warehouses: list[dict] = []
    warnings: list[str] = []
    draft_ids: dict[str, int] = {}
    any_fresh = False

    for option in options:
        result = _refresh_single_cluster(
            user,
            macrolocal_cluster_id=option["macrolocal_cluster_id"],
            cluster_id=option.get("cluster_id"),
            force=force,
        )
        if not result.get("ok"):
            warnings.append(f"{option['name']}: {result.get('error') or 'ошибка'}")
            continue
        if not result.get("cached"):
            any_fresh = True
        draft_ids[str(option["macrolocal_cluster_id"])] = int(result["draft_id"])
        all_warehouses.extend(result.get("warehouses") or [])

    if not all_warehouses:
        if warnings:
            return {"ok": False, "error": warnings[0]}
        return {"ok": False, "error": "Ozon не вернул склады ни для одного кластера."}

    all_warehouses.sort(
        key=lambda row: (
            0 if row["is_available"] else 1,
            str(row.get("cluster_name") or "").lower(),
            row.get("total_rank") if row.get("total_rank") is not None else 9999,
            row["name"].lower(),
        )
    )

    combined = {
        "ok": True,
        "cached": not any_fresh and not force,
        "all_clusters": True,
        "draft_id": None,
        "draft_ids": draft_ids,
        "sku": None,
        "cluster_name": "Все кластеры",
        "macrolocal_cluster_id": None,
        "cluster_id": None,
        "warehouses": all_warehouses,
        "summary": {
            "total": len(all_warehouses),
            "available": sum(1 for row in all_warehouses if row["is_available"]),
            "clusters": len(draft_ids),
        },
        "warnings": warnings,
    }
    _write_json_cache(cache_path, combined)
    return combined


def get_warehouse_timeslots(
    user,
    *,
    draft_id: int,
    macrolocal_cluster_id: int,
    cluster_id: int,
    storage_warehouse_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле."}

    if not date_from or not date_to:
        date_from, date_to = default_timeslot_period()

    cache_path = _timeslot_cache_path(user.id, int(draft_id), int(storage_warehouse_id))
    cached = _read_json_cache(cache_path, TIMESLOT_CACHE_SEC)
    if cached:
        cached = dict(cached)
        cached["ok"] = True
        cached["cached"] = True
        return cached

    try:
        data = fetch_draft_timeslots(
            user.ozon_client_id,
            user.ozon_api_key,
            draft_id=int(draft_id),
            macrolocal_cluster_id=int(macrolocal_cluster_id),
            cluster_id=int(cluster_id),
            storage_warehouse_id=int(storage_warehouse_id),
            date_from=date_from,
            date_to=date_to,
        )
    except RuntimeError as exc:
        return {"ok": False, "error": friendly_ozon_error(exc)}

    result = data.get("result") if isinstance(data.get("result"), dict) else data
    drop_off = result.get("drop_off_warehouse_timeslots") if isinstance(result, dict) else {}
    days_raw = drop_off.get("days") if isinstance(drop_off, dict) else []

    days: list[dict] = []
    total_slots = 0
    for day in days_raw or []:
        if not isinstance(day, dict):
            continue
        slots = []
        for slot in day.get("timeslots") or []:
            if not isinstance(slot, dict):
                continue
            slot_from = str(slot.get("from_in_timezone") or "")
            slot_to = str(slot.get("to_in_timezone") or "")
            if not slot_from or not slot_to:
                continue
            slots.append({"from": slot_from, "to": slot_to})
        if not slots:
            continue
        total_slots += len(slots)
        days.append(
            {
                "date": str(day.get("date_in_timezone") or ""),
                "timeslots": slots,
            }
        )

    payload = {
        "ok": True,
        "cached": False,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "days": days,
        "total_slots": total_slots,
    }
    _write_json_cache(cache_path, payload)
    return payload
