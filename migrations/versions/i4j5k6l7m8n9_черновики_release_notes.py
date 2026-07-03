"""Черновики release notes

Revision ID: i4j5k6l7m8n9
Revises: h3i4j5k6l7m8
Create Date: 2026-07-03 18:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "i4j5k6l7m8n9"
down_revision = "h3i4j5k6l7m8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("release_notes", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.create_index(
            batch_op.f("ix_release_notes_is_published"),
            ["is_published"],
            unique=False,
        )

    op.execute("UPDATE release_notes SET is_published = 1")


def downgrade():
    with op.batch_alter_table("release_notes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_release_notes_is_published"))
        batch_op.drop_column("is_published")
