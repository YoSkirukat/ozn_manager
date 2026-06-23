from flask import Blueprint

from app.routes.api.dashboard import dashboard_bp
from app.routes.api.orders import orders_api_bp
from app.routes.api.products import products_api_bp
from app.routes.api.shipments import shipments_api_bp
from app.routes.api.stocks import stocks_api_bp
from app.routes.api.scheduled_tasks import scheduled_tasks_api_bp
from app.routes.api.supply_planning import supply_planning_api_bp
from app.routes.api.promotions import promotions_api_bp
from app.routes.api.warehouse_slots import warehouse_slots_api_bp
from app.routes.api.notifications import notifications_api_bp

api_bp = Blueprint("api", __name__, url_prefix="/api")
api_bp.register_blueprint(dashboard_bp)
api_bp.register_blueprint(products_api_bp)
api_bp.register_blueprint(orders_api_bp)
api_bp.register_blueprint(shipments_api_bp)
api_bp.register_blueprint(stocks_api_bp)
api_bp.register_blueprint(supply_planning_api_bp)
api_bp.register_blueprint(scheduled_tasks_api_bp)
api_bp.register_blueprint(promotions_api_bp)
api_bp.register_blueprint(warehouse_slots_api_bp)
api_bp.register_blueprint(notifications_api_bp)
