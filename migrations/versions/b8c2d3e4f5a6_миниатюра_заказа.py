"""Миниатюра товара в заказе

Revision ID: b8c2d3e4f5a6
Revises: a7b1c2d3e4f5
Create Date: 2026-05-15 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b8c2d3e4f5a6"
down_revision = "a7b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("orders")}
    if "thumbnail_url" not in columns:
        with op.batch_alter_table("orders", schema=None) as batch_op:
            batch_op.add_column(sa.Column("thumbnail_url", sa.String(length=512), nullable=True))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("orders")}
    if "thumbnail_url" in columns:
        with op.batch_alter_table("orders", schema=None) as batch_op:
            batch_op.drop_column("thumbnail_url")
