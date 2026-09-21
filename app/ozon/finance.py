"""Финансовые операции Ozon Seller API."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from threading import Lock
from time import monotonic

from app.ozon.client import _post

logger = logging.getLogger(__name__)

# Начисления по отправлениям берём из нового финансового API.
# POST /v3/finance/transaction/list Ozon пометил как устаревший: он отвечает
# 400 «obsolete method cannot be used» и больше не отдаёт операции по отправлению,
# из-за чего в модалке заказа оставались только выручка и вознаграждение.
ACCRUAL_POSTINGS_PATH = "/v1/finance/accrual/postings"
ACCRUAL_TYPES_PATH = "/v1/finance/accrual/types"

# Ozon принимает от 1 до 200 номеров отправлений в одном запросе.
ACCRUAL_POSTINGS_BATCH_SIZE = 200
# Номера вида `12345678-0001-1`: усечённые и служебные Ozon отклоняет с ошибкой валидации.
POSTING_NUMBER_RE = re.compile(r"^\d{1,32}-\d{1,32}-\d{1,32}$")

ACCRUAL_TYPES_TTL_SECONDS = 6 * 60 * 60

_accrual_types_lock = Lock()
_accrual_types_cache: dict[str, tuple[float, dict[int, str]]] = {}


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


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal(0)


def accrual_amount(accrual: dict) -> Decimal:
    """Сумма начисления (Ozon отдаёт её в поле `accrued.amount`)."""
    if not isinstance(accrual, dict):
        return Decimal(0)
    accrued = accrual.get("accrued")
    if isinstance(accrued, dict):
        return _decimal(accrued.get("amount"))
    return _decimal(accrual.get("amount"))


def fetch_accrual_types(client_id: str, api_key: str) -> dict[int, str]:
    """Справочник типов начислений Ozon: id → название (как в кабинете продавца)."""
    key = str(client_id or "")
    now = monotonic()
    with _accrual_types_lock:
        cached = _accrual_types_cache.get(key)
    if cached and now - cached[0] < ACCRUAL_TYPES_TTL_SECONDS:
        return cached[1]

    try:
        data = _post(client_id, api_key, ACCRUAL_TYPES_PATH, {})
    except Exception:
        logger.warning(
            "Не удалось получить справочник типов начислений Ozon", exc_info=True
        )
        return dict(cached[1]) if cached else {}

    types: dict[int, str] = {}
    for item in data.get("accrual_types") or []:
        if not isinstance(item, dict):
            continue
        try:
            type_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        label = str(item.get("description") or item.get("name") or "").strip()
        if label:
            types[type_id] = label

    with _accrual_types_lock:
        _accrual_types_cache[key] = (monotonic(), types)
    return types


@dataclass(frozen=True)
class PostingAccruals:
    """Начисления по отправлениям и справочник типов для подписей строк."""

    by_posting: dict[str, list[dict]]
    types: dict[int, str]

    def accruals(self, posting_number: str) -> list[dict]:
        return self.by_posting.get(str(posting_number or "")) or []

    def label(self, type_id) -> str:
        try:
            key = int(type_id)
        except (TypeError, ValueError):
            return f"Начисление {type_id}"
        return self.types.get(key) or f"Начисление {key}"


def _accruals_from_response(data: dict) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for item in data.get("posting_accruals") or []:
        if not isinstance(item, dict):
            continue
        number = str(item.get("posting_number") or "").strip()
        if not number:
            continue
        result[number] = [a for a in (item.get("accruals") or []) if isinstance(a, dict)]
    return result


def _fetch_accrual_postings_chunk(
    client_id: str,
    api_key: str,
    posting_numbers: list[str],
) -> dict[str, list[dict]]:
    try:
        data = _post(
            client_id,
            api_key,
            ACCRUAL_POSTINGS_PATH,
            {"posting_numbers": posting_numbers},
        )
    except Exception:
        if len(posting_numbers) > 1:
            # Один отклонённый номер не должен обнулять начисления всего батча.
            logger.warning(
                "Ozon отклонил батч начислений (%s отправлений), пробуем по одному",
                len(posting_numbers),
                exc_info=True,
            )
            merged: dict[str, list[dict]] = {}
            for number in posting_numbers:
                merged.update(_fetch_accrual_postings_chunk(client_id, api_key, [number]))
            return merged
        logger.warning(
            "Нет начислений Ozon по отправлению %s", posting_numbers[0], exc_info=True
        )
        return {}
    return _accruals_from_response(data)


def load_posting_accruals(client_id: str, api_key: str, posting_numbers) -> PostingAccruals:
    """Начисления по отправлениям из /v1/finance/accrual/postings (батчами до 200)."""
    numbers: list[str] = []
    seen: set[str] = set()
    for raw in posting_numbers or []:
        number = str(raw or "").strip()
        if not number or number in seen or not POSTING_NUMBER_RE.match(number):
            continue
        seen.add(number)
        numbers.append(number)

    by_posting: dict[str, list[dict]] = {}
    for start in range(0, len(numbers), ACCRUAL_POSTINGS_BATCH_SIZE):
        chunk = numbers[start : start + ACCRUAL_POSTINGS_BATCH_SIZE]
        by_posting.update(_fetch_accrual_postings_chunk(client_id, api_key, chunk))

    if not client_id or not api_key:
        return PostingAccruals(by_posting=by_posting, types={})
    return PostingAccruals(by_posting=by_posting, types=fetch_accrual_types(client_id, api_key))


def is_acquiring_operation(op: dict) -> bool:
    op_type = str(op.get("operation_type") or "")
    if "Acquiring" in op_type:
        return True
    name = str(op.get("operation_type_name") or "").lower()
    return "эквайринг" in name
