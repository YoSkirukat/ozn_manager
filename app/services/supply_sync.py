"""Синхронизация заявок на поставку FBO из Ozon."""

from datetime import date

from app.db_sqlite import db_session_commit
from app.extensions import db
from app.models import Shipment, utcnow
from app.ozon.supplies import fetch_supply_orders
from app.services.change_log import log_change


def load_supplies_from_ozon(user, date_from: date, date_to: date) -> dict:
    if not user.has_ozon_credentials():
        return {"ok": False, "error": "Подключите Ozon API в профиле."}

    if date_from > date_to:
        return {"ok": False, "error": "Дата начала не может быть позже даты окончания."}

    if (date_to - date_from).days > 365:
        return {"ok": False, "error": "Максимальный период загрузки — 365 дней."}

    try:
        items = fetch_supply_orders(user.ozon_client_id, user.ozon_api_key, date_from, date_to)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    created = 0
    updated = 0
    now = utcnow()
    new_ozon_ids: list[str] = []
    status_changes: list[tuple[Shipment, str]] = []

    for item in items:
        shipment = Shipment.query.filter_by(
            user_id=user.id,
            ozon_supply_id=item["ozon_supply_id"],
        ).first()

        if shipment:
            old_status = str(shipment.status or "")
            shipment.order_number = item["order_number"]
            shipment.status = item["status"]
            shipment.supply_date = item["supply_date"]
            shipment.warehouse_name = item["warehouse_name"]
            shipment.dropoff_warehouse = item["dropoff_warehouse"]
            shipment.supplies_count = item["supplies_count"]
            shipment.raw_data = item["raw_data"]
            if old_status != str(item["status"] or ""):
                status_changes.append((shipment, old_status))
            updated += 1
        else:
            shipment = Shipment(
                user_id=user.id,
                ozon_supply_id=item["ozon_supply_id"],
                order_number=item["order_number"],
                status=item["status"],
                supply_date=item["supply_date"],
                warehouse_name=item["warehouse_name"],
                dropoff_warehouse=item["dropoff_warehouse"],
                supplies_count=item["supplies_count"],
                raw_data=item["raw_data"],
                created_at=now,
            )
            db.session.add(shipment)
            new_ozon_ids.append(item["ozon_supply_id"])
            created += 1

    log_change(
        user_id=user.id,
        action_type="update",
        entity_type="shipment",
        entity_id=0,
        old_value=None,
        new_value={
            "sync": "ozon",
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "created": created,
            "updated": updated,
            "total": len(items),
        },
    )
    db_session_commit()

    if new_ozon_ids or status_changes:
        from app.services.notifications_service import (
            notify_new_shipments,
            notify_shipment_status_changed,
        )

        if new_ozon_ids:
            new_shipments = Shipment.query.filter(
                Shipment.user_id == user.id,
                Shipment.ozon_supply_id.in_(new_ozon_ids),
            ).all()
            notify_new_shipments(user, new_shipments)

        for shipment, old_status in status_changes:
            notify_shipment_status_changed(user, shipment, old_status)

    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "total": len(items),
        "message": (
            f"Загружено поставок: {len(items)} "
            f"(новых {created}, обновлено {updated})."
        ),
    }
