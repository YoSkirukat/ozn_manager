"""Закупочные цены из внешнего файла

Revision ID: f6a0c3d7e8b9
Revises: e5f9b2c4d5a6
Create Date: 2026-05-15 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "f6a0c3d7e8b9"
down_revision = "e5f9b2c4d5a6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    user_columns = {c["name"] for c in insp.get_columns("users")}
    if "purchase_prices_url" not in user_columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(sa.Column("purchase_prices_url", sa.String(length=1024), nullable=True))

    product_columns = {c["name"] for c in insp.get_columns("products")}
    if "purchase_price" not in product_columns:
        with op.batch_alter_table("products", schema=None) as batch_op:
            batch_op.add_column(sa.Column("purchase_price", sa.Numeric(12, 2), nullable=True))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    product_columns = {c["name"] for c in insp.get_columns("products")}
    if "purchase_price" in product_columns:
        with op.batch_alter_table("products", schema=None) as batch_op:
            batch_op.drop_column("purchase_price")

    user_columns = {c["name"] for c in insp.get_columns("users")}
    if "purchase_prices_url" in user_columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.drop_column("purchase_prices_url")
