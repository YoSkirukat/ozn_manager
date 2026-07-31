"""Эксперименты с ценами

Revision ID: l7m8n9o0p1q2
Revises: k6l7m8n9o0p1
Create Date: 2026-07-30 17:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "l7m8n9o0p1q2"
down_revision = "k6l7m8n9o0p1"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "price_experiments" not in tables:
        op.create_table(
            "price_experiments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=256), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_price_experiments_user_id", "price_experiments", ["user_id"])
        op.create_index("ix_price_experiments_status", "price_experiments", ["status"])

    if "price_experiment_items" not in tables:
        op.create_table(
            "price_experiment_items",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("experiment_id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["experiment_id"], ["price_experiments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("experiment_id", "product_id", name="uq_price_experiment_item_product"),
        )
        op.create_index("ix_price_experiment_items_experiment_id", "price_experiment_items", ["experiment_id"])
        op.create_index("ix_price_experiment_items_product_id", "price_experiment_items", ["product_id"])

    if "price_experiment_snapshots" not in tables:
        op.create_table(
            "price_experiment_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("item_id", sa.Integer(), nullable=False),
            sa.Column("snapshot_date", sa.Date(), nullable=False),
            sa.Column("stock_fbo", sa.Integer(), nullable=False),
            sa.Column("stock_fbs", sa.Integer(), nullable=False),
            sa.Column("purchase_price", sa.Numeric(12, 2), nullable=True),
            sa.Column("prices", sa.JSON(), nullable=True),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["item_id"], ["price_experiment_items.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("item_id", "snapshot_date", name="uq_price_experiment_snapshot_item_date"),
        )
        op.create_index("ix_price_experiment_snapshots_item_id", "price_experiment_snapshots", ["item_id"])
        op.create_index("ix_price_experiment_snapshots_snapshot_date", "price_experiment_snapshots", ["snapshot_date"])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "price_experiment_snapshots" in tables:
        op.drop_table("price_experiment_snapshots")
    if "price_experiment_items" in tables:
        op.drop_table("price_experiment_items")
    if "price_experiments" in tables:
        op.drop_table("price_experiments")
