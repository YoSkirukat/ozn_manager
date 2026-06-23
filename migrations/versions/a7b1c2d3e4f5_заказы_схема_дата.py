"""Схема и дата заказа

Revision ID: a7b1c2d3e4f5
Revises: f6a0c3d7e8b9
Create Date: 2026-05-15 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a7b1c2d3e4f5"
down_revision = "f6a0c3d7e8b9"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("orders")}

    with op.batch_alter_table("orders", schema=None) as batch_op:
        if "scheme" not in columns:
            batch_op.add_column(
                sa.Column("scheme", sa.String(length=8), nullable=False, server_default="FBS")
            )
        if "order_date" not in columns:
            batch_op.add_column(sa.Column("order_date", sa.DateTime(timezone=True), nullable=True))
        if "raw_data" not in columns:
            batch_op.add_column(sa.Column("raw_data", sa.JSON(), nullable=True))

    op.execute("UPDATE orders SET order_date = created_at WHERE order_date IS NULL")

    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.alter_column("order_date", existing_type=sa.DateTime(timezone=True), nullable=False)

    indexes = {idx["name"] for idx in insp.get_indexes("orders")}
    if "ix_orders_user_order_date" not in indexes:
        with op.batch_alter_table("orders", schema=None) as batch_op:
            batch_op.create_index("ix_orders_user_order_date", ["user_id", "order_date"])

    constraints = {c["name"] for c in insp.get_unique_constraints("orders")}
    if "uq_orders_user_ozon" not in constraints:
        with op.batch_alter_table("orders", schema=None) as batch_op:
            batch_op.create_unique_constraint("uq_orders_user_ozon", ["user_id", "ozon_order_id"])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    indexes = {idx["name"] for idx in insp.get_indexes("orders")}
    constraints = {c["name"] for c in insp.get_unique_constraints("orders")}

    with op.batch_alter_table("orders", schema=None) as batch_op:
        if "uq_orders_user_ozon" in constraints:
            batch_op.drop_constraint("uq_orders_user_ozon", type_="unique")
        if "ix_orders_user_order_date" in indexes:
            batch_op.drop_index("ix_orders_user_order_date")
        batch_op.drop_column("raw_data")
        batch_op.drop_column("order_date")
        batch_op.drop_column("scheme")
