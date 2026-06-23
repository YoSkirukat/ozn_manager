"""Роли и имя пользователя

Revision ID: 7928dc5f74dd
Revises: 8db1db33dc6b
Create Date: 2026-05-15 13:18:23.896676

"""
from alembic import op
import sqlalchemy as sa


revision = "7928dc5f74dd"
down_revision = "8db1db33dc6b"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("users")}

    with op.batch_alter_table("users", schema=None) as batch_op:
        if "display_name" not in columns:
            batch_op.add_column(sa.Column("display_name", sa.String(length=120), nullable=True))
        if "role" not in columns:
            batch_op.add_column(
                sa.Column("role", sa.String(length=16), nullable=False, server_default="user")
            )
        indexes = {i["name"] for i in insp.get_indexes("users")}
        if "ix_users_role" not in indexes:
            batch_op.create_index(batch_op.f("ix_users_role"), ["role"], unique=False)

    op.execute("UPDATE users SET role = 'admin' WHERE username = 'admin'")
    op.execute("UPDATE users SET display_name = username WHERE display_name IS NULL")


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_role"))
        batch_op.drop_column("role")
        batch_op.drop_column("display_name")
