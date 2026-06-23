"""Активация пользователей

Revision ID: b2a8e1f04c31
Revises: c465c4ae8c90
Create Date: 2026-05-15 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b2a8e1f04c31"
down_revision = "c465c4ae8c90"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("users")}

    if "is_active" not in columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false())
            )
            indexes = {i["name"] for i in insp.get_indexes("users")}
            if "ix_users_is_active" not in indexes:
                batch_op.create_index(batch_op.f("ix_users_is_active"), ["is_active"], unique=False)

    # Существующие пользователи остаются активными
    op.execute("UPDATE users SET is_active = 1")


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_is_active"))
        batch_op.drop_column("is_active")
