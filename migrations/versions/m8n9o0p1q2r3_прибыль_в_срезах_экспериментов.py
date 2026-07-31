"""Прибыль/наценка в срезах экспериментов

Revision ID: m8n9o0p1q2r3
Revises: l7m8n9o0p1q2
Create Date: 2026-07-31 10:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "m8n9o0p1q2r3"
down_revision = "l7m8n9o0p1q2"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "price_experiment_snapshots" not in set(insp.get_table_names()):
        return
    columns = {c["name"] for c in insp.get_columns("price_experiment_snapshots")}
    if "profit_markup" not in columns:
        with op.batch_alter_table("price_experiment_snapshots", schema=None) as batch_op:
            batch_op.add_column(sa.Column("profit_markup", sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "price_experiment_snapshots" not in set(insp.get_table_names()):
        return
    columns = {c["name"] for c in insp.get_columns("price_experiment_snapshots")}
    if "profit_markup" in columns:
        with op.batch_alter_table("price_experiment_snapshots", schema=None) as batch_op:
            batch_op.drop_column("profit_markup")
