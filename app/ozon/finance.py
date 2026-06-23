"""Финансовые операции Ozon Seller API."""

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.ozon.client import _post

SERVICE_LABELS = {
    "MarketplaceServiceItemDirectFlowLogistic": "Услуги доставки",
    "MarketplaceServiceItemReturnFlowLogistic": "Услуги доставки",
    "MarketplaceServiceItemRedistributionLastMileCourier": "Доставка до места выдачи партнёрами",
    "MarketplaceServiceItemDelivToCustomer": "Доставка покупателю",
    "MarketplaceServiceItemDropoff": "Обработка отправления",
    "MarketplaceServiceItemPickup": "Обработка отправления",
    "ItemAgentServiceStarsMembership": "Звёздные товары",
    "MarketplaceAgencyFeeAggregator3plRFBS": (
        "Агентское вознаграждение за доставку Партнёрами Ozon на схеме realFBS"
    ),
    "MarketplaceServiceRedistributionOfDeliveryServicesRFBS": (
        "Услуги доставки Партнёрами Ozon на схеме realFBS"
    ),
    "MarketplaceSellerReexposureDeliveryReturnOperation": "Перечисление за доставку от покупателя",
}


def service_label(code: str) -> str:
    if not code:
        return "Услуга"
    return SERVICE_LABELS.get(code, code)


def related_posting_numbers(posting_number: str) -> list[str]:
    """Номера для поиска: полный и родительский (без суффикса -N).

    Эквайринг часто привязан к заказу `0120460840-0135`, а отправление — `0120460840-0135-1`.
    """
    if not posting_number:
        return []
    numbers = [posting_number]
    if posting_number.count("-") >= 2:
        parent = posting_number.rsplit("-", 1)[0]
        suffix = posting_number.rsplit("-", 1)[-1]
        if parent and parent != posting_number and suffix.isdigit():
            numbers.append(parent)
    return numbers


def _parse_operation_date(value: str | None) -> str:
    if not value:
        return "—"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            raw = value.replace("Z", "+00:00") if "Z" in value and "+" not in value else value
            dt = datetime.fromisoformat(raw) if "T" in raw or "+" in raw else datetime.strptime(value, fmt)
            return dt.strftime("%d.%m.%Y")
        except ValueError:
            continue
    return str(value)[:10]


def _order_calendar_date(order_date) -> date:
    if isinstance(order_date, date) and not isinstance(order_date, datetime):
        return order_date
    if hasattr(order_date, "date"):
        return order_date.date()
    return date.today()


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    last_day = calendar.monthrange(year, month)[1]
    return (
        f"{year:04d}-{month:02d}-01T00:00:00.000Z",
        f"{year:04d}-{month:02d}-{last_day:02d}T23:59:59.999Z",
    )


def _search_windows(order_date) -> list[tuple[str, str]]:
    """Календарные месяцы для поиска: Ozon API допускает не больше одного месяца."""
    center = _order_calendar_date(order_date)
    windows = [_month_bounds(center.year, center.month)]
    if center.month == 12:
        windows.append(_month_bounds(center.year + 1, 1))
    else:
        windows.append(_month_bounds(center.year, center.month + 1))
    return windows


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal(0)


def _operation_score(op: dict) -> float:
    score = 0.0
    if _decimal(op.get("accruals_for_sale")):
        score += 1000
    if _decimal(op.get("sale_commission")):
        score += 1000
    score += len(op.get("services") or []) * 10
    score += float(abs(_decimal(op.get("amount"))))
    return score


def _merge_operations(operations: list[dict]) -> list[dict]:
    merged: dict[int, dict] = {}
    for op in operations:
        if not isinstance(op, dict):
            continue
        op_id = op.get("operation_id")
        key = op_id if op_id is not None else id(op)
        prev = merged.get(key)
        if prev is None or _operation_score(op) > _operation_score(prev):
            merged[key] = op
    return list(merged.values())


def _matches_posting(op: dict, allowed_postings: set[str]) -> bool:
    posting = op.get("posting") if isinstance(op.get("posting"), dict) else {}
    op_posting = str(posting.get("posting_number") or "")
    return bool(op_posting) and op_posting in allowed_postings


def _fetch_transactions_window(
    client_id: str,
    api_key: str,
    start: str,
    end: str,
    *,
    posting_number: str | None = None,
) -> list[dict]:
    operations: list[dict] = []
    page = 1
    while True:
        filter_body = {
            "date": {"from": start, "to": end},
            "transaction_type": "all",
        }
        if posting_number:
            filter_body["posting_number"] = posting_number
        try:
            data = _post(
                client_id,
                api_key,
                "/v3/finance/transaction/list",
                {
                    "filter": filter_body,
                    "page": page,
                    "page_size": 1000,
                },
            )
        except Exception:
            break
        result = data.get("result") or {}
        batch = result.get("operations") or []
        operations.extend(op for op in batch if isinstance(op, dict))
        page_count = int(result.get("page_count") or 1)
        if page >= page_count:
            break
        page += 1
    return operations


def _is_partial_delivery_operation(op: dict) -> bool:
    """Ozon иногда отдаёт урезанную операцию доставки только с логистикой."""
    if is_acquiring_operation(op):
        return False
    op_type = str(op.get("operation_type") or "")
    if "Delivered" not in op_type and "Delivery" not in op_type:
        return False
    if _decimal(op.get("accruals_for_sale")) or _decimal(op.get("sale_commission")):
        return False
    amount = abs(_decimal(op.get("amount")))
    services = [s for s in (op.get("services") or []) if isinstance(s, dict)]
    if not services or amount == 0:
        return False
    services_sum = sum(abs(_decimal(s.get("price"))) for s in services)
    return amount <= services_sum + Decimal("0.01")


def _needs_broad_fetch(operations: list[dict]) -> bool:
    if not operations:
        return True
    return any(_is_partial_delivery_operation(op) for op in operations)


def operations_look_complete(operations: list[dict]) -> bool:
    """Основные начисления (выручка/комиссия) уже есть в ответе Ozon."""
    if not operations or _needs_broad_fetch(operations):
        return False
    for op in operations:
        if is_acquiring_operation(op):
            continue
        if _decimal(op.get("accruals_for_sale")) or _decimal(op.get("sale_commission")):
            return True
    return False


def fetch_posting_transactions(
    client_id: str,
    api_key: str,
    posting_number: str,
    order_date,
) -> list[dict]:
    """Операции по отправлению из /v3/finance/transaction/list."""
    if not order_date or not posting_number:
        return []

    allowed_postings = set(related_posting_numbers(posting_number))
    collected: list[dict] = []

    for start, end in _search_windows(order_date):
        window_ops: list[dict] = []
        for pn in allowed_postings:
            window_ops.extend(
                _fetch_transactions_window(client_id, api_key, start, end, posting_number=pn)
            )

        filtered = [op for op in window_ops if _matches_posting(op, allowed_postings)]
        if _needs_broad_fetch(filtered):
            broad_ops = _fetch_transactions_window(client_id, api_key, start, end)
            filtered = [op for op in broad_ops if _matches_posting(op, allowed_postings)]

        collected.extend(filtered)

    return _merge_operations(collected)


def is_acquiring_operation(op: dict) -> bool:
    op_type = str(op.get("operation_type") or "")
    if "Acquiring" in op_type:
        return True
    name = str(op.get("operation_type_name") or "").lower()
    return "эквайринг" in name
