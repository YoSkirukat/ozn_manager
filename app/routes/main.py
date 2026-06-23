from datetime import date, datetime

from flask import Blueprint, make_response, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import and_, or_

from app.authz import is_admin
from app.datetime_fmt import utc_bounds_for_local_dates
from app.models import Order, Product, ReleaseNote, Shipment, SUPPLY_ACTIVE_STATUSES, SUPPLY_HIDDEN_LIST_STATUSES
from app.services.orders_filters import resolve_orders_filters, scheme_options, status_options
from app.services.orders_period import get_orders_period, save_orders_period, save_shipments_period
from app.version import get_app_version


def _parse_date_param(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None

main_bp = Blueprint("main", __name__)

PAGES = {
    "/": ("partials/dashboard.html", "index.html", "Главная — Ozon Manager"),
    "/products": ("partials/products.html", "pages/products.html", "Товары — Ozon Manager"),
    "/orders": ("partials/orders.html", "pages/orders.html", "Заказы — Ozon Manager"),
    "/shipments": ("partials/shipments.html", "pages/shipments.html", "Поставки — Ozon Manager"),
    "/reports": ("partials/reports.html", "pages/reports.html", "Отчёты — Ozon Manager"),
    "/reports/stock": ("partials/stock.html", "pages/stock.html", "Остатки товаров — Ozon Manager"),
    "/reports/returns": ("partials/returns.html", "pages/returns.html", "Возвраты — Ozon Manager"),
    "/analytics": ("partials/analytics.html", "pages/analytics.html", "Аналитика — Ozon Manager"),
    "/analytics/supply-planning": (
        "partials/supply_planning.html",
        "pages/supply_planning.html",
        "Планирование поставки — Ozon Manager",
    ),
    "/analytics/promotions": (
        "partials/promotions.html",
        "pages/promotions.html",
        "Товары в акциях — Ozon Manager",
    ),
    "/analytics/warehouse-slots": (
        "partials/warehouse_slots.html",
        "pages/warehouse_slots.html",
        "Склады и слоты — Ozon Manager",
    ),
    "/changelog": ("partials/changelog.html", "pages/changelog.html", "Журнал изменений — Ozon Manager"),
}


def _render_page(path_key: str, **ctx):
    partial, full, title = PAGES[path_key]
    ctx.setdefault("page_title", title)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return make_response(render_template(partial, **ctx))
    return render_template(full, **ctx)


@main_bp.route("/")
@login_required
def index():
    from app.services.orders_chart import default_chart_period, get_chart_prefs

    chart_from, chart_to = default_chart_period()
    chart_metric, chart_compare = get_chart_prefs()
    return _render_page(
        "/",
        chart_date_from=chart_from,
        chart_date_to=chart_to,
        chart_metric=chart_metric,
        chart_compare=chart_compare,
    )


@main_bp.route("/products")
@login_required
def products():
    items = (
        Product.query.filter_by(user_id=current_user.id)
        .order_by(Product.name.asc())
        .all()
    )
    product_actions: dict[str, list[str]] = {}
    product_promo_prices: dict[str, float] = {}
    if current_user.has_ozon_credentials():
        try:
            from app.services.product_actions import fetch_product_promotions_data

            promo_data = fetch_product_promotions_data(
                current_user.ozon_client_id,
                current_user.ozon_api_key,
            )
            product_actions = promo_data.get("titles") or {}
            product_promo_prices = promo_data.get("prices") or {}
        except Exception:
            product_actions = {}
            product_promo_prices = {}

    from app.services.product_actions import attach_product_sale_prices

    attach_product_sale_prices(items, product_promo_prices)
    return _render_page(
        "/products",
        products=items,
        product_actions=product_actions,
        product_promo_prices=product_promo_prices,
        has_ozon=current_user.has_ozon_credentials(),
    )


@main_bp.route("/orders")
@login_required
def orders():
    date_from = _parse_date_param(request.args.get("from"))
    date_to = _parse_date_param(request.args.get("to"))

    if not date_from or not date_to:
        date_from, date_to = get_orders_period()

    selected_statuses, selected_schemes = resolve_orders_filters()

    items = []
    if date_from and date_to:
        save_orders_period(date_from, date_to)
        start, end = utc_bounds_for_local_dates(date_from, date_to)
        query = Order.query.filter(
            Order.user_id == current_user.id,
            Order.order_date >= start,
            Order.order_date <= end,
        )
        if selected_statuses:
            query = query.filter(Order.status.in_(selected_statuses))
        if selected_schemes:
            query = query.filter(Order.scheme.in_(selected_schemes))
        items = query.order_by(Order.order_date.desc()).all()
        if items:
            from app.db_sqlite import db_session_commit
            from app.services.order_details import attach_order_margins
            from app.services.order_promotions import (
                apply_product_promotions_batch,
                fetch_known_promotion_titles,
            )

            known_titles: set[str] = set()
            if current_user.has_ozon_credentials():
                try:
                    known_titles = fetch_known_promotion_titles(
                        current_user.ozon_client_id,
                        current_user.ozon_api_key,
                    )
                except Exception:
                    known_titles = set()

            if apply_product_promotions_batch(
                items,
                current_user.id,
                current_user,
                known_titles=known_titles,
            ):
                db_session_commit()

            # Страница /orders должна открываться быстро: без внешних API в рендере.
            attach_order_margins(items, current_user, use_transactions=False)
            from app.services.order_details import attach_order_product_cells
            from app.services.order_returns import attach_post_delivery_return_flags

            attach_order_product_cells(items, current_user.id)
            attach_post_delivery_return_flags(items, current_user.id)

    return _render_page(
        "/orders",
        orders=items,
        has_ozon=current_user.has_ozon_credentials(),
        date_from=date_from,
        date_to=date_to,
        status_options=status_options(),
        scheme_options=scheme_options(),
        selected_statuses=selected_statuses,
        selected_schemes=selected_schemes,
        filters_active=bool(selected_statuses or selected_schemes),
    )


@main_bp.route("/shipments")
@login_required
def shipments():
    date_from = _parse_date_param(request.args.get("from"))
    date_to = _parse_date_param(request.args.get("to"))

    items = []
    if date_from and date_to:
        save_shipments_period(date_from, date_to)
        start, end = utc_bounds_for_local_dates(date_from, date_to)
        items = (
            Shipment.query.filter(
                Shipment.user_id == current_user.id,
                Shipment.status.notin_(SUPPLY_HIDDEN_LIST_STATUSES),
                or_(
                    and_(
                        Shipment.supply_date >= start,
                        Shipment.supply_date <= end,
                    ),
                    Shipment.status.in_(SUPPLY_ACTIVE_STATUSES),
                ),
            )
            .order_by(Shipment.supply_date.desc())
            .all()
        )

    return _render_page(
        "/shipments",
        shipments=items,
        has_ozon=current_user.has_ozon_credentials(),
        date_from=date_from,
        date_to=date_to,
    )


@main_bp.route("/reports")
@login_required
def reports():
    from flask import redirect

    return redirect("/reports/stock")


@main_bp.route("/reports/stock")
@login_required
def reports_stock():
    from app.ozon.stocks import compute_stock_summary, group_products, group_warehouses
    from app.services.stock_report import enrich_product_stock_list, get_stock_report_cache

    warehouses = []
    products = []
    stock_summary = None
    rows = get_stock_report_cache(current_user.id)
    if rows:
        warehouses = group_warehouses(rows)
        products = enrich_product_stock_list(current_user.id, group_products(rows))
        stock_summary = compute_stock_summary(rows, warehouses)

    return _render_page(
        "/reports/stock",
        warehouses=warehouses,
        products=products,
        stock_summary=stock_summary,
        has_ozon=current_user.has_ozon_credentials(),
        has_data=bool(warehouses),
    )


@main_bp.route("/reports/returns")
@login_required
def reports_returns():
    from app.services.returns_period import resolve_returns_period, save_returns_period
    from app.services.returns_report import build_returns_report, get_returns_report_cache

    date_from = _parse_date_param(request.args.get("from"))
    date_to = _parse_date_param(request.args.get("to"))

    if not date_from or not date_to:
        date_from, date_to = resolve_returns_period()
    else:
        save_returns_period(date_from, date_to)

    returns = []
    summary = {"return_count": 0}
    load_error = None

    if current_user.has_ozon_credentials():
        force_refresh = request.args.get("refresh", "").strip().lower() in ("1", "true", "yes")
        cached = get_returns_report_cache(current_user.id)
        cache_matches = (
            not force_refresh
            and cached
            and cached.get("date_from") == date_from.isoformat()
            and cached.get("date_to") == date_to.isoformat()
        )
        if cache_matches:
            returns = cached.get("returns") or []
            summary = cached.get("summary") or summary
        else:
            report = build_returns_report(current_user, date_from, date_to)
            if report.get("ok"):
                returns = report.get("returns") or []
                summary = report.get("summary") or summary
            else:
                load_error = report.get("error") or "Не удалось загрузить возвраты."

    return _render_page(
        "/reports/returns",
        returns=returns,
        summary=summary,
        load_error=load_error,
        has_ozon=current_user.has_ozon_credentials(),
        has_data=bool(returns),
        date_from=date_from,
        date_to=date_to,
    )


@main_bp.route("/analytics")
@login_required
def analytics():
    from flask import redirect

    return redirect("/analytics/supply-planning")


@main_bp.route("/analytics/supply-planning")
@login_required
def analytics_supply_planning():
    from datetime import timedelta

    from app.datetime_fmt import local_today
    from app.services.supply_planning import build_supply_planning_report, list_warehouses_with_stock

    warehouses = list_warehouses_with_stock(current_user)
    warehouse_name = (request.args.get("warehouse") or "").strip()
    date_from = _parse_date_param(request.args.get("from"))
    date_to = _parse_date_param(request.args.get("to"))

    if not date_from or not date_to:
        today = local_today()
        date_to = today
        date_from = today - timedelta(days=29)

    report = None
    report_error = None
    if warehouse_name and request.args.get("from") and request.args.get("to"):
        result = build_supply_planning_report(
            current_user,
            warehouse_name,
            date_from,
            date_to,
        )
        if result.get("ok"):
            report = result
        else:
            report_error = result.get("error") or "Не удалось сформировать отчёт."

    return _render_page(
        "/analytics/supply-planning",
        warehouses=warehouses,
        selected_warehouse=warehouse_name,
        date_from=date_from,
        date_to=date_to,
        report=report,
        report_error=report_error,
        has_ozon=current_user.has_ozon_credentials(),
        report_requested=bool(warehouse_name and request.args.get("from") and request.args.get("to")),
    )


@main_bp.route("/analytics/promotions")
@login_required
def analytics_promotions():
    from app.services.product_actions import build_promotions_report

    promotions = []
    summary = {"promotion_count": 0, "product_count": 0}
    load_error = None

    if current_user.has_ozon_credentials():
        report = build_promotions_report(current_user)
        if report.get("ok"):
            promotions = report.get("promotions") or []
            summary = report.get("summary") or summary
        else:
            load_error = report.get("error") or "Не удалось загрузить акции."

    return _render_page(
        "/analytics/promotions",
        promotions=promotions,
        summary=summary,
        load_error=load_error,
        has_ozon=current_user.has_ozon_credentials(),
        has_data=bool(promotions),
    )


@main_bp.route("/analytics/warehouse-slots")
@login_required
def analytics_warehouse_slots():
    from app.services.warehouse_slots import list_macrolocal_clusters

    clusters = []
    load_error = None
    if current_user.has_ozon_credentials():
        report = list_macrolocal_clusters(current_user)
        if report.get("ok"):
            clusters = report.get("clusters") or []
        else:
            load_error = report.get("error") or "Не удалось загрузить кластеры."

    return _render_page(
        "/analytics/warehouse-slots",
        clusters=clusters,
        load_error=load_error,
        has_ozon=current_user.has_ozon_credentials(),
    )


@main_bp.route("/changelog")
@login_required
def changelog():
    releases = ReleaseNote.query.order_by(ReleaseNote.released_at.desc()).all()
    return _render_page(
        "/changelog",
        releases=releases,
        current_version=get_app_version(),
        is_admin=is_admin(),
    )
