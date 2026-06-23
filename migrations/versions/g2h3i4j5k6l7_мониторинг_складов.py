"""Мониторинг доступности складов FBO

Revision ID: g2h3i4j5k6l7
Revises: 0f1a2b3c4d5e
Create Date: 2026-06-22 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "g2h3i4j5k6l7"
down_revision = "0f1a2b3c4d5e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "warehouse_slot_watches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("macrolocal_cluster_id", sa.Integer(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        sa.Column("storage_warehouse_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_name", sa.String(length=256), nullable=False),
        sa.Column("cluster_name", sa.String(length=256), nullable=False),
        sa.Column("last_availability_state", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "macrolocal_cluster_id",
            "storage_warehouse_id",
            name="uq_warehouse_slot_watch_user_warehouse",
        ),
    )
    with op.batch_alter_table("warehouse_slot_watches", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_warehouse_slot_watches_storage_warehouse_id"),
            ["storage_warehouse_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_warehouse_slot_watches_user_id"),
            ["user_id"],
            unique=False,
        )


def downgrade():
    op.drop_table("warehouse_slot_watches")
