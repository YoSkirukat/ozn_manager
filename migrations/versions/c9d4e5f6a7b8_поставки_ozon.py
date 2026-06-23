"""Поставки FBO из Ozon

Revision ID: c9d4e5f6a7b8
Revises: b8c2d3e4f5a6
Create Date: 2026-05-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c9d4e5f6a7b8"
down_revision = "b8c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("shipments")
    op.create_table(
        "shipments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ozon_supply_id", sa.String(length=64), nullable=False),
        sa.Column("order_number", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("supply_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("warehouse_name", sa.String(length=256), nullable=True),
        sa.Column("dropoff_warehouse", sa.String(length=256), nullable=True),
        sa.Column("supplies_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "ozon_supply_id", name="uq_shipments_user_ozon"),
    )
    with op.batch_alter_table("shipments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_shipments_user_id"), ["user_id"], unique=False)
        batch_op.create_index("ix_shipments_user_supply_date", ["user_id", "supply_date"], unique=False)


def downgrade():
    op.drop_table("shipments")
    op.create_table(
        "shipments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("tracking_number", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("shipments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_shipments_order_id"), ["order_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_shipments_user_id"), ["user_id"], unique=False)
        batch_op.create_index("ix_shipments_user_order", ["user_id", "order_id"], unique=False)
