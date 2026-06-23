"""Уведомления: настройки и журнал

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-06-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b3c4d5e6f7a8"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_slug", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "event_slug", name="uq_notification_user_slug"),
    )
    with op.batch_alter_table("notification_settings", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_notification_settings_event_slug"), ["event_slug"], unique=False)
        batch_op.create_index(batch_op.f("ix_notification_settings_user_id"), ["user_id"], unique=False)

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_slug", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_url", sa.String(length=512), nullable=False, server_default="/"),
        sa.Column("entity_type", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("entity_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "event_slug",
            "entity_type",
            "entity_id",
            name="uq_notification_entity",
        ),
    )
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_notifications_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_notifications_event_slug"), ["event_slug"], unique=False)
        batch_op.create_index(batch_op.f("ix_notifications_read_at"), ["read_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_notifications_user_id"), ["user_id"], unique=False)
        batch_op.create_index(
            "ix_notifications_user_read_created",
            ["user_id", "read_at", "created_at"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_index("ix_notifications_user_read_created")
        batch_op.drop_index(batch_op.f("ix_notifications_user_id"))
        batch_op.drop_index(batch_op.f("ix_notifications_read_at"))
        batch_op.drop_index(batch_op.f("ix_notifications_event_slug"))
        batch_op.drop_index(batch_op.f("ix_notifications_created_at"))
    op.drop_table("notifications")

    with op.batch_alter_table("notification_settings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_notification_settings_user_id"))
        batch_op.drop_index(batch_op.f("ix_notification_settings_event_slug"))
    op.drop_table("notification_settings")
