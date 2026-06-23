"""Остатки FBO и FBS отдельно

Revision ID: e5f9b2c4d5a6
Revises: d4e8a1b2c3f0
Create Date: 2026-05-15 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "e5f9b2c4d5a6"
down_revision = "d4e8a1b2c3f0"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("products")}

    with op.batch_alter_table("products", schema=None) as batch_op:
        if "stock_fbo" not in columns:
            batch_op.add_column(
                sa.Column("stock_fbo", sa.Integer(), nullable=False, server_default="0")
            )
        if "stock_fbs" not in columns:
            batch_op.add_column(
                sa.Column("stock_fbs", sa.Integer(), nullable=False, server_default="0")
            )

    if "stock" in columns:
        op.execute(
            "UPDATE products SET stock_fbo = COALESCE(stock, 0) WHERE stock_fbo = 0 AND stock_fbs = 0"
        )
        with op.batch_alter_table("products", schema=None) as batch_op:
            batch_op.drop_column("stock")


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("products")}

    with op.batch_alter_table("products", schema=None) as batch_op:
        if "stock" not in columns:
            batch_op.add_column(
                sa.Column("stock", sa.Integer(), nullable=False, server_default="0")
            )

    if "stock_fbo" in columns and "stock_fbs" in columns:
        op.execute(
            "UPDATE products SET stock = COALESCE(stock_fbo, 0) + COALESCE(stock_fbs, 0)"
        )

    with op.batch_alter_table("products", schema=None) as batch_op:
        if "stock_fbs" in columns:
            batch_op.drop_column("stock_fbs")
        if "stock_fbo" in columns:
            batch_op.drop_column("stock_fbo")
