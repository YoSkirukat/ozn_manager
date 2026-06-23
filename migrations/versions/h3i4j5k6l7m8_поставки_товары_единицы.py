"""Колонки товаров и единиц в поставках

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-06-22 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "h3i4j5k6l7m8"
down_revision = "g2h3i4j5k6l7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("shipments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sku_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("units_total", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("shipments", schema=None) as batch_op:
        batch_op.drop_column("units_total")
        batch_op.drop_column("sku_count")
