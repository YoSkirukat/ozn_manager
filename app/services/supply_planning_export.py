"""Экспорт планирования поставки в XLS (Excel 97)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import quote

from app.datetime_fmt import to_local

SEND_EXPORT_HEADERS = ("Артикул", "Количество")
OZON_EXPORT_HEADERS = ("артикул", "имя (необязательно)", "количество")


def _sanitize_warehouse_for_filename(warehouse_name: str) -> str:
    text = str(warehouse_name or "").strip() or "склад"
    text = re.sub(r"[^\w.\-]+", "_", text, flags=re.UNICODE)
    return text.strip("._") or "склад"


def build_supply_planning_export_filename(warehouse_name: str) -> str:
    """Имя файла: ГРИВНО_РФЦ_10.06.2026_18-35-15.xls"""
    now = to_local(datetime.now(timezone.utc))
    warehouse = _sanitize_warehouse_for_filename(warehouse_name)
    date_part = now.strftime("%d.%m.%Y")
    time_part = now.strftime("%H-%M-%S")
    return f"{warehouse}_{date_part}_{time_part}.xls"


def content_disposition_attachment(filename: str) -> str:
    ascii_name = re.sub(r"[^\x20-\x7E]+", "_", filename) or "supply_planning.xls"
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'


def build_supply_planning_send_xls(rows: list[tuple[str, int]]) -> bytes:
    import xlwt

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Поставка")

    for col, header in enumerate(SEND_EXPORT_HEADERS):
        sheet.write(0, col, header)

    for row_index, (article, quantity) in enumerate(rows, start=1):
        sheet.write(row_index, 0, article)
        sheet.write(row_index, 1, int(quantity))

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_supply_planning_ozon_xls(rows: list[tuple[str, str, int]]) -> bytes:
    import xlwt

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Поставка")

    for col, header in enumerate(OZON_EXPORT_HEADERS):
        sheet.write(0, col, header)

    for row_index, (offer_id, name, quantity) in enumerate(rows, start=1):
        sheet.write(row_index, 0, offer_id)
        sheet.write(row_index, 1, name)
        sheet.write(row_index, 2, int(quantity))

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
