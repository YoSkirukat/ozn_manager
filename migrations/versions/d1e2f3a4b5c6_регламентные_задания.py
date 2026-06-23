"""Регламентные задания: настройки и журнал запусков

Revision ID: d1e2f3a4b5c6
Revises: c9d4e5f6a7b8
Create Date: 2026-05-22 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "d1e2f3a4b5c6"
down_revision = "c9d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "scheduled_task_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_slug", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("interval_key", sa.String(length=32), nullable=False, server_default="every_1h"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "task_slug", name="uq_scheduled_task_user_slug"),
    )
    with op.batch_alter_table("scheduled_task_settings", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_scheduled_task_settings_task_slug"), ["task_slug"], unique=False)
        batch_op.create_index(batch_op.f("ix_scheduled_task_settings_user_id"), ["user_id"], unique=False)

    op.create_table(
        "scheduled_task_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_slug", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("scheduled_task_runs", schema=None) as batch_op:
        batch_op.create_index("ix_scheduled_task_runs_task_started", ["task_slug", "started_at"], unique=False)
        batch_op.create_index("ix_scheduled_task_runs_user_started", ["user_id", "started_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_scheduled_task_runs_started_at"), ["started_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_scheduled_task_runs_task_slug"), ["task_slug"], unique=False)
        batch_op.create_index(batch_op.f("ix_scheduled_task_runs_user_id"), ["user_id"], unique=False)


def downgrade():
    op.drop_table("scheduled_task_runs")
    op.drop_table("scheduled_task_settings")
