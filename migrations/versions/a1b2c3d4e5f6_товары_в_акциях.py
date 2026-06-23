"""Счётчик товаров в акциях на дашборде

Revision ID: a1b2c3d4e5f6
Revises: e7f8a9b0c1d2
Create Date: 2026-06-17 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    user_columns = {c["name"] for c in insp.get_columns("users")}
    if "products_in_promotions_count" not in user_columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("products_in_promotions_count", sa.Integer(), nullable=False, server_default="0"),
            )


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    user_columns = {c["name"] for c in insp.get_columns("users")}
    if "products_in_promotions_count" in user_columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.drop_column("products_in_promotions_count")
