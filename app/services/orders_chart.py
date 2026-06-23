"""Агрегация заказов по дням для графика на дашборде."""

from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import request, session

from app.datetime_fmt import local_calendar_date, local_today, utc_bounds_for_local_dates
from app.extensions import db
from app.models import Order

SESSION_DASHBOARD_CHART_PREFS = "dashboard_chart_prefs"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def default_chart_period() -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=13), today


def _day_range(date_from: date, date_to: date) -> list[date]:
    days: list[date] = []
    current = date_from
    while current <= date_to:
        days.append(current)
        current += timedelta(days=1)
    return days


def _aggregate_by_day(
    user_id: int,
    date_from: date,
    date_to: date,
    metric: str,
) -> dict[date, float]:
    start, end = utc_bounds_for_local_dates(date_from, date_to)
    orders = (
        Order.query.filter(
            Order.user_id == user_id,
            Order.order_date >= start,
            Order.order_date <= end,
        )
        .all()
    )

    result: dict[date, float] = defaultdict(float)
    for order in orders:
        day = local_calendar_date(order.order_date)
        if not day or day < date_from or day > date_to:
            continue
        if metric == "amount":
            result[day] += float(order.total or 0)
        else:
            result[day] += 1.0
    return dict(result)


def _format_period_label(date_from: date, date_to: date) -> str:
    return f"{date_from.strftime('%d.%m')} – {date_to.strftime('%d.%m')}"


def _day_count_amount_maps(
    user_id: int,
    date_from: date,
    date_to: date,
) -> tuple[dict[date, int], dict[date, float]]:
    start, end = utc_bounds_for_local_dates(date_from, date_to)
    orders = (
        Order.query.filter(
            Order.user_id == user_id,
            Order.order_date >= start,
            Order.order_date <= end,
        )
        .all()
    )

    count_map: dict[date, int] = defaultdict(int)
    amount_map: dict[date, float] = defaultdict(float)
    for order in orders:
        day = local_calendar_date(order.order_date)
        if not day or day < date_from or day > date_to:
            continue
        count_map[day] += 1
        amount_map[day] += float(order.total or 0)
    return dict(count_map), dict(amount_map)


def _comparison(current: float, previous: float, *, as_amount: bool = False) -> dict:
    delta = current - previous
    if as_amount:
        delta = round(delta, 2)
    else:
        delta = int(round(delta))
    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"
    else:
        direction = "neutral"
    return {"delta": delta, "direction": direction}


def build_today_summary(user_id: int) -> dict:
    """Сводка за сегодня: количество и сумма, сравнение с вчера и с тем же днём неделю назад."""
    today = local_today()
    yesterday = today - timedelta(days=1)
    last_week = today - timedelta(days=7)

    count_map, amount_map = _day_count_amount_maps(user_id, last_week, today)

    today_count = count_map.get(today, 0)
    today_amount = amount_map.get(today, 0.0)
    yesterday_count = count_map.get(yesterday, 0)
    yesterday_amount = amount_map.get(yesterday, 0.0)
    last_week_count = count_map.get(last_week, 0)
    last_week_amount = amount_map.get(last_week, 0.0)

    return {
        "date": today.isoformat(),
        "count": {
            "value": today_count,
            "vs_yesterday": _comparison(today_count, yesterday_count),
            "vs_last_week": _comparison(today_count, last_week_count),
        },
        "amount": {
            "value": round(today_amount, 2),
            "vs_yesterday": _comparison(today_amount, yesterday_amount, as_amount=True),
            "vs_last_week": _comparison(today_amount, last_week_amount, as_amount=True),
        },
    }


def build_daily_stats(
    user_id: int,
    date_from: date,
    date_to: date,
) -> list[dict]:
    """По каждому дню периода: заказы и суммы + те же показатели неделю назад."""
    lookup_from = date_from - timedelta(days=7)
    count_map, amount_map = _day_count_amount_maps(user_id, lookup_from, date_to)
    stats: list[dict] = []
    for day in _day_range(date_from, date_to):
        week_ago = day - timedelta(days=7)
        stats.append(
            {
                "date": day.isoformat(),
                "label": day.strftime("%d.%m"),
                "count": count_map.get(day, 0),
                "amount": round(amount_map.get(day, 0.0), 2),
                "week_ago_label": week_ago.strftime("%d.%m"),
                "week_ago_count": count_map.get(week_ago, 0),
                "week_ago_amount": round(amount_map.get(week_ago, 0.0), 2),
            }
        )
    return stats


def build_orders_chart(
    user_id: int,
    date_from: date,
    date_to: date,
    metric: str = "count",
    compare: bool = False,
) -> dict:
    if date_from > date_to:
        return {"ok": False, "error": "Дата начала позже даты окончания."}

    if (date_to - date_from).days > 365:
        return {"ok": False, "error": "Период не может быть больше 365 дней."}

    metric = "amount" if metric == "amount" else "count"
    days = _day_range(date_from, date_to)
    current_map = _aggregate_by_day(user_id, date_from, date_to, metric)

    labels = [d.strftime("%d.%m") for d in days]
    current = [current_map.get(d, 0.0) for d in days]

    payload = {
        "ok": True,
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "metric": metric,
        "compare": compare,
        "labels": labels,
        "current": current,
        "current_label": _format_period_label(date_from, date_to),
    }

    daily_stats = build_daily_stats(user_id, date_from, date_to)
    payload["daily_stats"] = daily_stats

    if compare:
        week_ago_key = "week_ago_amount" if metric == "amount" else "week_ago_count"
        payload["previous"] = [float(s[week_ago_key]) for s in daily_stats]
        payload["previous_label"] = "Неделю назад"
    else:
        payload["previous"] = None
        payload["previous_label"] = None

    payload["today_summary"] = build_today_summary(user_id)

    from app.services.dashboard_orders_breakdown import build_orders_breakdown

    payload.update(build_orders_breakdown(user_id, date_from, date_to))
    return payload


def _normalize_metric(value: str | None) -> str:
    if (value or "").strip().lower() in ("amount", "rub", "rubles", "money"):
        return "amount"
    return "count"


def _normalize_compare(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def get_chart_prefs() -> tuple[str, bool]:
    raw = session.get(SESSION_DASHBOARD_CHART_PREFS) or {}
    metric = _normalize_metric(raw.get("metric"))
    return metric, bool(raw.get("compare"))


def save_chart_prefs(metric: str, compare: bool) -> None:
    session[SESSION_DASHBOARD_CHART_PREFS] = {
        "metric": _normalize_metric(metric),
        "compare": bool(compare),
    }


def resolve_chart_params(
    date_from_raw: str | None,
    date_to_raw: str | None,
    metric_raw: str | None,
    compare_raw: str | None,
) -> tuple[date, date, str, bool]:
    date_from = _parse_date(date_from_raw)
    date_to = _parse_date(date_to_raw)
    if not date_from or not date_to:
        date_from, date_to = default_chart_period()

    if "metric" in request.args or "compare" in request.args:
        metric = _normalize_metric(metric_raw)
        compare = _normalize_compare(compare_raw)
        save_chart_prefs(metric, compare)
    else:
        metric, compare = get_chart_prefs()

    return date_from, date_to, metric, compare
