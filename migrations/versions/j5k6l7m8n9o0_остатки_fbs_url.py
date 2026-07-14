"""Ссылка на файл остатков FBS в профиле

Revision ID: j5k6l7m8n9o0
Revises: i4j5k6l7m8n9
Create Date: 2026-07-14 18:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "j5k6l7m8n9o0"
down_revision = "i4j5k6l7m8n9"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    user_columns = {c["name"] for c in insp.get_columns("users")}
    if "fbs_stocks_url" not in user_columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(sa.Column("fbs_stocks_url", sa.String(length=1024), nullable=True))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    user_columns = {c["name"] for c in insp.get_columns("users")}
    if "fbs_stocks_url" in user_columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.drop_column("fbs_stocks_url")
