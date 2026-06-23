"""Комиссии FBO/FBS у товаров

Revision ID: e7f8a9b0c1d2
Revises: d1e2f3a4b5c6
Create Date: 2026-05-25 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "e7f8a9b0c1d2"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("products")}

    with op.batch_alter_table("products", schema=None) as batch_op:
        if "commission_fbo" not in columns:
            batch_op.add_column(sa.Column("commission_fbo", sa.Numeric(12, 2), nullable=True))
        if "commission_fbs" not in columns:
            batch_op.add_column(sa.Column("commission_fbs", sa.Numeric(12, 2), nullable=True))
        if "commission_details" not in columns:
            batch_op.add_column(sa.Column("commission_details", sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("products")}

    with op.batch_alter_table("products", schema=None) as batch_op:
        if "commission_details" in columns:
            batch_op.drop_column("commission_details")
        if "commission_fbs" in columns:
            batch_op.drop_column("commission_fbs")
        if "commission_fbo" in columns:
            batch_op.drop_column("commission_fbo")
