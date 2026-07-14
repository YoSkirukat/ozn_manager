"""Ссылка и склад для остатков FBS

Revision ID: k6l7m8n9o0p1
Revises: j5k6l7m8n9o0
Create Date: 2026-07-14 18:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "k6l7m8n9o0p1"
down_revision = "j5k6l7m8n9o0"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    user_columns = {c["name"] for c in insp.get_columns("users")}
    if "fbs_warehouse_id" not in user_columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(sa.Column("fbs_warehouse_id", sa.String(length=64), nullable=True))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    user_columns = {c["name"] for c in insp.get_columns("users")}
    if "fbs_warehouse_id" in user_columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.drop_column("fbs_warehouse_id")
