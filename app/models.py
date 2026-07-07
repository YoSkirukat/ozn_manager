from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    ROLE_ADMIN = "admin"
    ROLE_USER = "user"

    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(120), nullable=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(16), nullable=False, default=ROLE_USER, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=False, index=True)
    ozon_client_id = db.Column(db.String(64), nullable=True)
    ozon_api_key = db.Column(db.String(256), nullable=True)
    ozon_company_name = db.Column(db.String(256), nullable=True)
    ozon_connected_at = db.Column(db.DateTime(timezone=True), nullable=True)
    ozon_key_active = db.Column(db.Boolean, nullable=True)
    purchase_prices_url = db.Column(db.String(1024), nullable=True)
    products_in_promotions_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    products = db.relationship("Product", back_populates="user", cascade="all, delete-orphan")
    orders = db.relationship("Order", back_populates="user", cascade="all, delete-orphan")
    shipments = db.relationship("Shipment", back_populates="user", cascade="all, delete-orphan")
    reports = db.relationship("Report", back_populates="user", cascade="all, delete-orphan")
    analytics = db.relationship("Analytics", back_populates="user", cascade="all, delete-orphan")
    change_logs = db.relationship("ChangeLog", back_populates="user", cascade="all, delete-orphan")
    scheduled_task_settings = db.relationship(
        "ScheduledTaskSetting",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    scheduled_task_runs = db.relationship(
        "ScheduledTaskRun",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    notification_settings = db.relationship(
        "NotificationSetting",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    notifications = db.relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    warehouse_slot_watches = db.relationship(
        "WarehouseSlotWatch",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role == self.ROLE_ADMIN

    def label(self) -> str:
        return self.display_name or self.username

    def has_ozon_credentials(self) -> bool:
        return bool(self.ozon_client_id and self.ozon_api_key)

    def ozon_is_active(self) -> bool:
        return self.ozon_key_active is True


class Product(db.Model):
    __tablename__ = "products"
    __table_args__ = (
        db.UniqueConstraint("user_id", "ozon_product_id", name="uq_products_user_ozon"),
        db.Index("ix_products_user_offer", "user_id", "offer_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ozon_product_id = db.Column(db.String(64), nullable=False)
    offer_id = db.Column(db.String(128), nullable=False, default="")
    barcode = db.Column(db.String(128), nullable=True)
    thumbnail_url = db.Column(db.String(512), nullable=True)
    sku = db.Column(db.String(64), nullable=True)
    name = db.Column(db.String(512), nullable=False)
    price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    purchase_price = db.Column(db.Numeric(12, 2), nullable=True)
    stock_fbo = db.Column(db.Integer, nullable=False, default=0)
    stock_fbs = db.Column(db.Integer, nullable=False, default=0)
    commission_fbo = db.Column(db.Numeric(12, 2), nullable=True)
    commission_fbs = db.Column(db.Numeric(12, 2), nullable=True)
    commission_details = db.Column(db.JSON, nullable=True)
    raw_data = db.Column(db.JSON, nullable=True)
    last_sync = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User", back_populates="products")

    def barcode_display(self) -> str:
        return self.barcode or "—"

    def ozon_marketplace_product_slug(self) -> str | None:
        text = str(self.barcode or "").strip()
        if not text:
            return None
        if text.upper().startswith("OZN"):
            text = text[3:].strip()
        if not text or not text.isdigit():
            return None
        return text

    def ozon_marketplace_url(self) -> str | None:
        slug = self.ozon_marketplace_product_slug()
        if not slug:
            return None
        return f"https://www.ozon.ru/product/{slug}"

    def purchase_price_display(self) -> str:
        from app.money_fmt import format_money_ru

        if self.purchase_price is None:
            return "—"
        return format_money_ru(self.purchase_price)

    def commission_display(self, scheme: str) -> str:
        from app.money_fmt import format_money_display_text, format_money_ru

        if isinstance(self.commission_details, dict):
            block = self.commission_details.get(scheme)
            if isinstance(block, dict) and block.get("has_data"):
                from app.services.product_commissions import _enrich_commission_block

                enriched = _enrich_commission_block(block, self.effective_sale_price())
                display = enriched.get("total_display")
                if display:
                    return format_money_display_text(str(display))
        value = self.commission_fbo if scheme == "fbo" else self.commission_fbs
        if value is None:
            return "—"
        return format_money_ru(value)

    def has_commission_detail(self, scheme: str) -> bool:
        if not isinstance(self.commission_details, dict):
            return False
        block = self.commission_details.get(scheme)
        return isinstance(block, dict) and bool(block.get("has_data"))

    def profit_markup_scheme_rows(self) -> list[tuple[str, str, bool]]:
        from app.services.product_profit import profit_markup_scheme_rows

        return profit_markup_scheme_rows(self)

    def can_show_profit_markup(self) -> bool:
        if self.purchase_price is None:
            return False
        return self.has_commission_detail("fbo") or self.has_commission_detail("fbs")

    def active_promotions(self) -> list[str]:
        raw = self.raw_data if isinstance(self.raw_data, dict) else {}
        promos = raw.get("active_promotions")
        if not isinstance(promos, list):
            return []
        return [str(title) for title in promos if title]

    def promotion_titles(self, live_map: dict[str, list[str]] | None = None) -> list[str]:
        if live_map is not None:
            live = live_map.get(self.ozon_product_id, [])
            if live:
                return live
        return self.active_promotions()

    def promotion_price(self, live_map: dict[str, float] | None = None) -> float | None:
        if live_map is not None:
            value = live_map.get(self.ozon_product_id)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None

        raw = self.raw_data if isinstance(self.raw_data, dict) else {}
        value = raw.get("promotion_price")
        if value is None:
            return None
        try:
            price = float(value)
        except (TypeError, ValueError):
            return None
        return price if price > 0 else None

    def effective_sale_price(self, promo_prices_map: dict[str, float] | None = None) -> float:
        attached = getattr(self, "_effective_sale_price", None)
        if attached is not None:
            return float(attached)

        promo = self.promotion_price(promo_prices_map)
        if promo is not None:
            return promo
        return float(self.price or 0)

    def uses_promotional_sale_price(self) -> bool:
        attached = getattr(self, "_is_promotional_price", None)
        if attached is not None:
            return bool(attached)
        return self.promotion_price() is not None

    def to_dict(self):
        return {
            "id": self.id,
            "ozon_product_id": self.ozon_product_id,
            "offer_id": self.offer_id,
            "barcode": self.barcode,
            "thumbnail_url": self.thumbnail_url,
            "name": self.name,
            "price": float(self.price) if self.price is not None else 0,
            "purchase_price": float(self.purchase_price) if self.purchase_price is not None else None,
            "stock_fbo": self.stock_fbo,
            "stock_fbs": self.stock_fbs,
            "commission_fbo": float(self.commission_fbo) if self.commission_fbo is not None else None,
            "commission_fbs": float(self.commission_fbs) if self.commission_fbs is not None else None,
            "last_sync": self.last_sync.isoformat() if self.last_sync else None,
        }


ORDER_STATUS_DELIVERED = "delivered"
HOME_COUNTRY_NAME = "Россия"

CURRENCY_SYMBOLS = {
    "RUB": "₽",
    "BYN": "BYN",
    "KZT": "₸",
    "USD": "$",
    "EUR": "€",
}

ORDER_STATUS_LABELS = {
    "awaiting_registration": "Ожидает регистрации",
    "awaiting_approve": "Ожидает подтверждения",
    "awaiting_packaging": "Ожидает сборки",
    "awaiting_deliver": "Готов к отгрузке",
    "awaiting_pickup": "Ожидает получения",
    "delivering": "Доставляется",
    "delivered": "Доставлен",
    "cancelled": "Отменён",
    "not_accepted": "Не принят",
    "arbitration": "Арбитраж",
    "client_arbitration": "Клиентский арбитраж",
}

ORDER_STATUS_BADGE = {
    "awaiting_packaging": "ready",
    "awaiting_deliver": "ready",
    "delivering": "shipping",
    "delivered": "done",
    "cancelled": "cancelled",
    "awaiting_registration": "pending",
    "awaiting_approve": "pending",
    "awaiting_pickup": "pending",
}


class Order(db.Model):
    __tablename__ = "orders"
    __table_args__ = (
        db.UniqueConstraint("user_id", "ozon_order_id", name="uq_orders_user_ozon"),
        db.Index("ix_orders_user_order_date", "user_id", "order_date"),
    )

    SCHEME_FBO = "FBO"
    SCHEME_FBS = "FBS"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ozon_order_id = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(64), nullable=False, default="unknown")
    scheme = db.Column(db.String(8), nullable=False, default=SCHEME_FBS)
    total = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    order_date = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    thumbnail_url = db.Column(db.String(512), nullable=True)
    raw_data = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship("User", back_populates="orders")

    def status_display(self) -> str:
        return ORDER_STATUS_LABELS.get(self.status, self.status)

    def status_badge_class(self) -> str:
        return ORDER_STATUS_BADGE.get(self.status, "default")

    def scheme_display(self) -> str:
        return self.scheme or self.SCHEME_FBS

    def products_list(self) -> list:
        raw = self.raw_data if isinstance(self.raw_data, dict) else {}
        products = raw.get("products") or []
        if not products:
            financial = raw.get("financial_data")
            if isinstance(financial, dict):
                products = financial.get("products") or []
            elif isinstance(financial, list):
                products = financial
        return [p for p in products if isinstance(p, dict)]

    def primary_product(self) -> dict:
        items = self.products_list()
        return items[0] if items else {}

    def product_image_url(self) -> str | None:
        if self.thumbnail_url:
            return self.thumbnail_url

        raw = self.raw_data if isinstance(self.raw_data, dict) else {}
        for key in ("product_thumbnail", "thumbnail", "image"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for product in self.products_list():
            for key in ("picture_url", "image_url", "primary_image", "photo", "picture"):
                value = product.get(key)
                if isinstance(value, list) and value:
                    value = value[0]
                if isinstance(value, str) and value.strip():
                    return value.strip()

        from app.services.order_images import resolve_thumbnail_url

        return resolve_thumbnail_url(self.user_id, raw)

    def product_cell(self) -> dict:
        cached = getattr(self, "_product_cell", None)
        if isinstance(cached, dict):
            return cached

        from app.services.order_details import attach_order_product_cells

        attach_order_product_cells([self], self.user_id)
        cached = getattr(self, "_product_cell", None)
        if isinstance(cached, dict):
            return cached

        return {
            "title": "—",
            "name": "—",
            "offer_id": "—",
            "barcode": "—",
        }

    def promotion_purchase_info(self) -> dict:
        from app.services.order_promotions import promotion_info_for_primary_product

        return promotion_info_for_primary_product(self)

    def promotion_purchase_labels(self) -> list[str]:
        info = self.promotion_purchase_info()
        if not info.get("in_promotion"):
            return []
        return [str(title) for title in (info.get("titles") or []) if title]

    def bought_on_promotion(self) -> bool:
        return bool(self.promotion_purchase_info().get("in_promotion"))

    def has_refund_after_delivery(self) -> bool:
        from app.services.order_returns import order_has_refund_after_delivery

        return order_has_refund_after_delivery(self)

    def has_post_delivery_return(self) -> bool:
        return self.has_refund_after_delivery()

    def refund_after_delivery_tooltip(self) -> str:
        from app.services.order_returns import refund_after_delivery_tooltip

        return refund_after_delivery_tooltip(self)

    def order_margin(self, user=None):
        if hasattr(self, "_list_margin"):
            return self._list_margin
        from app.services.order_details import compute_order_margin

        return compute_order_margin(self, user=user or self.user, use_transactions=False)

    def delivery_country(self) -> str:
        from app.services.order_destination import resolve_delivery_country

        raw = self.raw_data if isinstance(self.raw_data, dict) else {}
        return resolve_delivery_country(raw)

    def is_international(self) -> bool:
        from app.services.order_destination import is_international_delivery

        raw = self.raw_data if isinstance(self.raw_data, dict) else {}
        return is_international_delivery(raw)

    def customer_currency(self) -> str:
        products = self.products_list()
        for product in products:
            code = str(product.get("currency_code") or "").strip().upper()
            if code:
                return code
        raw = self.raw_data if isinstance(self.raw_data, dict) else {}
        financial = raw.get("financial_data")
        if isinstance(financial, dict):
            for product in financial.get("products") or []:
                if not isinstance(product, dict):
                    continue
                code = str(product.get("currency_code") or "").strip().upper()
                if code:
                    return code
        return "RUB"

    def customer_currency_symbol(self) -> str:
        code = self.customer_currency()
        return CURRENCY_SYMBOLS.get(code, code or "₽")

    def to_dict(self):
        return {
            "id": self.id,
            "ozon_order_id": self.ozon_order_id,
            "status": self.status,
            "status_display": self.status_display(),
            "scheme": self.scheme,
            "total": float(self.total) if self.total is not None else 0,
            "order_date": self.order_date.isoformat() if self.order_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# Не показываем на странице «Поставки»
SUPPLY_HIDDEN_LIST_STATUSES = frozenset({
    "CANCELLED",
})

# Активные заявки показываем на странице поставок даже вне выбранного периода
SUPPLY_ACTIVE_STATUSES = frozenset({
    "DATA_FILLING",
    "READY_TO_SUPPLY",
    "ACCEPTED_AT_SUPPLY_WAREHOUSE",
    "IN_TRANSIT",
    "ACCEPTED_AT_STORAGE_WAREHOUSE",
    "ACCEPTANCE_AT_STORAGE_WAREHOUSE",
    "REPORTS_FILLING",
    "REPORTS_CONFIRMATION_AWAITING",
    "REPORT_REJECTED",
    "REJECTED_AT_SUPPLY_WAREHOUSE",
})

SUPPLY_STATUS_LABELS = {
    "COMPLETED": "Завершена",
    "CANCELLED": "Отменена",
    "DATA_FILLING": "Заполнение данных",
    "READY_TO_SUPPLY": "Готово к отгрузке",
    "ACCEPTED_AT_SUPPLY_WAREHOUSE": "Принята на точке отгрузки",
    "IN_TRANSIT": "В пути",
    "ACCEPTED_AT_STORAGE_WAREHOUSE": "Принята на складе",
    "ACCEPTANCE_AT_STORAGE_WAREHOUSE": "Приёмка на складе",
    "REPORTS_FILLING": "Заполнение отчётов",
    "REPORTS_CONFIRMATION_AWAITING": "Ожидает подтверждения отчётов",
    "REPORT_REJECTED": "Отчёт отклонён",
    "REJECTED_AT_SUPPLY_WAREHOUSE": "Отклонена на точке отгрузки",
}

SUPPLY_STATUS_BADGE = {
    "COMPLETED": "done",
    "CANCELLED": "cancelled",
    "IN_TRANSIT": "shipping",
    "READY_TO_SUPPLY": "ready",
    "DATA_FILLING": "pending",
    "ACCEPTED_AT_SUPPLY_WAREHOUSE": "shipping",
    "ACCEPTED_AT_STORAGE_WAREHOUSE": "shipping",
    "ACCEPTANCE_AT_STORAGE_WAREHOUSE": "shipping",
    "REPORTS_FILLING": "pending",
    "REPORTS_CONFIRMATION_AWAITING": "pending",
    "REPORT_REJECTED": "cancelled",
    "REJECTED_AT_SUPPLY_WAREHOUSE": "cancelled",
}


class Shipment(db.Model):
    """Заявка на поставку FBO на склад Ozon."""

    __tablename__ = "shipments"
    __table_args__ = (
        db.UniqueConstraint("user_id", "ozon_supply_id", name="uq_shipments_user_ozon"),
        db.Index("ix_shipments_user_supply_date", "user_id", "supply_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ozon_supply_id = db.Column(db.String(64), nullable=False)
    order_number = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(64), nullable=False, default="unknown")
    supply_date = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    warehouse_name = db.Column(db.String(256), nullable=True)
    dropoff_warehouse = db.Column(db.String(256), nullable=True)
    supplies_count = db.Column(db.Integer, nullable=False, default=0)
    sku_count = db.Column(db.Integer, nullable=True)
    units_total = db.Column(db.Integer, nullable=True)
    raw_data = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship("User", back_populates="shipments")

    def status_display(self) -> str:
        return SUPPLY_STATUS_LABELS.get(self.status, self.status)

    def status_badge_class(self) -> str:
        return SUPPLY_STATUS_BADGE.get(self.status, "default")

    def to_dict(self):
        return {
            "id": self.id,
            "ozon_supply_id": self.ozon_supply_id,
            "order_number": self.order_number,
            "status": self.status,
            "status_display": self.status_display(),
            "supply_date": self.supply_date.isoformat() if self.supply_date else None,
            "warehouse_name": self.warehouse_name,
            "dropoff_warehouse": self.dropoff_warehouse,
            "supplies_count": self.supplies_count,
            "sku_count": self.sku_count,
            "units_total": self.units_total,
        }


class Report(db.Model):
    __tablename__ = "reports"
    __table_args__ = (
        db.Index("ix_reports_user_type", "user_id", "report_type"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    report_type = db.Column(db.String(64), nullable=False)
    file_path = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    user = db.relationship("User", back_populates="reports")

    def to_dict(self):
        return {
            "id": self.id,
            "report_type": self.report_type,
            "file_path": self.file_path,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Analytics(db.Model):
    __tablename__ = "analytics"
    __table_args__ = (
        db.Index("ix_analytics_user_period", "user_id", "period"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    period = db.Column(db.String(32), nullable=False)  # week, month, etc.
    sales_data = db.Column(db.JSON, nullable=False, default=dict)
    views_data = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship("User", back_populates="analytics")

    def to_dict(self):
        return {
            "id": self.id,
            "period": self.period,
            "sales_data": self.sales_data or {},
            "views_data": self.views_data or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ReleaseNote(db.Model):
    """Публичный журнал обновлений сервиса (release notes)."""

    __tablename__ = "release_notes"

    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.String(32), unique=True, nullable=False, index=True)
    released_at = db.Column(db.Date, nullable=False, index=True)
    items = db.Column(db.JSON, nullable=False, default=list)
    is_published = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    @property
    def items_list(self) -> list:
        return self.items if isinstance(self.items, list) else []


class ChangeLog(db.Model):
    """Аудит изменений сущностей (внутренний, не публичный журнал)."""

    __tablename__ = "change_log"
    __table_args__ = (
        db.Index("ix_change_log_entity", "entity_type", "entity_id"),
        db.Index("ix_change_log_user_entity", "user_id", "entity_type", "entity_id"),
        db.Index("ix_change_log_timestamp", "timestamp"),
    )

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    action_type = db.Column(db.String(16), nullable=False)  # create, update, delete
    entity_type = db.Column(db.String(32), nullable=False)  # product, order, shipment, ...
    entity_id = db.Column(db.Integer, nullable=False)
    old_value = db.Column(db.JSON, nullable=True)
    new_value = db.Column(db.JSON, nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1)

    user = db.relationship("User", back_populates="change_logs")

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "user_id": self.user_id,
            "action_type": self.action_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "version": self.version,
        }


class ScheduledTaskSetting(db.Model):
    """Настройки регламентного задания для пользователя."""

    __tablename__ = "scheduled_task_settings"
    __table_args__ = (
        db.UniqueConstraint("user_id", "task_slug", name="uq_scheduled_task_user_slug"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    task_slug = db.Column(db.String(64), nullable=False, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    interval_key = db.Column(db.String(32), nullable=False, default="every_1h")
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    user = db.relationship("User", back_populates="scheduled_task_settings")


class ScheduledTaskRun(db.Model):
    """Журнал запусков регламентных заданий."""

    __tablename__ = "scheduled_task_runs"
    __table_args__ = (
        db.Index("ix_scheduled_task_runs_user_started", "user_id", "started_at"),
        db.Index("ix_scheduled_task_runs_task_started", "task_slug", "started_at"),
    )

    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_ERROR = "error"
    STATUS_SKIPPED = "skipped"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    task_slug = db.Column(db.String(64), nullable=False, index=True)
    started_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    status = db.Column(db.String(16), nullable=False, default=STATUS_RUNNING)
    message = db.Column(db.Text, nullable=True)
    details = db.Column(db.JSON, nullable=True)

    user = db.relationship("User", back_populates="scheduled_task_runs")


class NotificationSetting(db.Model):
    """Включение/выключение типов уведомлений для пользователя."""

    __tablename__ = "notification_settings"
    __table_args__ = (
        db.UniqueConstraint("user_id", "event_slug", name="uq_notification_user_slug"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    event_slug = db.Column(db.String(64), nullable=False, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    user = db.relationship("User", back_populates="notification_settings")


class Notification(db.Model):
    """Уведомление пользователя."""

    __tablename__ = "notifications"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "event_slug",
            "entity_type",
            "entity_id",
            name="uq_notification_entity",
        ),
        db.Index("ix_notifications_user_read_created", "user_id", "read_at", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    event_slug = db.Column(db.String(64), nullable=False, index=True)
    title = db.Column(db.String(256), nullable=False)
    body = db.Column(db.Text, nullable=False, default="")
    target_url = db.Column(db.String(512), nullable=False, default="/")
    entity_type = db.Column(db.String(64), nullable=False, default="")
    entity_id = db.Column(db.Integer, nullable=False, default=0)
    payload = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    read_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    user = db.relationship("User", back_populates="notifications")

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "event_slug": self.event_slug,
            "title": self.title,
            "body": self.body,
            "target_url": self.target_url,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "payload": self.payload if isinstance(self.payload, dict) else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "is_read": self.is_read,
        }


class WarehouseSlotWatch(db.Model):
    """Склад, за доступностью которого следит пользователь."""

    __tablename__ = "warehouse_slot_watches"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "macrolocal_cluster_id",
            "storage_warehouse_id",
            name="uq_warehouse_slot_watch_user_warehouse",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    macrolocal_cluster_id = db.Column(db.Integer, nullable=False)
    cluster_id = db.Column(db.Integer, nullable=False)
    storage_warehouse_id = db.Column(db.Integer, nullable=False, index=True)
    warehouse_name = db.Column(db.String(256), nullable=False, default="—")
    cluster_name = db.Column(db.String(256), nullable=False, default="—")
    last_availability_state = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    user = db.relationship("User", back_populates="warehouse_slot_watches")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "macrolocal_cluster_id": self.macrolocal_cluster_id,
            "cluster_id": self.cluster_id,
            "storage_warehouse_id": self.storage_warehouse_id,
            "warehouse_name": self.warehouse_name,
            "cluster_name": self.cluster_name,
            "last_availability_state": self.last_availability_state,
            "watch_key": f"{self.macrolocal_cluster_id}:{self.storage_warehouse_id}",
        }
