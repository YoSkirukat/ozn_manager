"""Остатки FBS по складам

Revision ID: n9o0p1q2r3s4
Revises: m8n9o0p1q2r3
Create Date: 2026-09-23 12:30:00.000000

"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "n9o0p1q2r3s4"
down_revision = "m8n9o0p1q2r3"
branch_labels = None
depends_on = None


def _migrate_legacy_settings(bind) -> None:
    """Переносит одиночную настройку остатков FBS из users в fbs_stock_sources."""
    insp = sa.inspect(bind)
    user_columns = {c["name"] for c in insp.get_columns("users")}
    if "fbs_stocks_url" not in user_columns:
        return

    warehouse_column = "fbs_warehouse_id" if "fbs_warehouse_id" in user_columns else "NULL"
    rows = bind.execute(
        sa.text(
            "SELECT id, fbs_stocks_url, "
            f"{warehouse_column} AS warehouse_id FROM users "
            "WHERE fbs_stocks_url IS NOT NULL AND TRIM(fbs_stocks_url) <> ''"
        )
    ).fetchall()
    if not rows:
        return

    now = datetime.now(timezone.utc)
    payload: list[dict] = []
    for row in rows:
        user_id = int(row[0])
        already = bind.execute(
            sa.text("SELECT COUNT(*) FROM fbs_stock_sources WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).scalar()
        if already:
            continue
        warehouse_id = (row[2] or "").strip() if row[2] is not None else ""
        payload.append(
            {
                "user_id": user_id,
                "warehouse_id": warehouse_id,
                "warehouse_name": None,
                "stocks_url": row[1],
                "created_at": now,
                "updated_at": now,
            }
        )

    if not payload:
        return

    sources_table = sa.table(
        "fbs_stock_sources",
        sa.column("user_id", sa.Integer),
        sa.column("warehouse_id", sa.String),
        sa.column("warehouse_name", sa.String),
        sa.column("stocks_url", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(sources_table, payload)


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "fbs_stock_sources" not in tables:
        op.create_table(
            "fbs_stock_sources",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("warehouse_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("warehouse_name", sa.String(length=256), nullable=True),
            sa.Column("stocks_url", sa.String(length=1024), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id",
                "warehouse_id",
                name="uq_fbs_stock_source_user_warehouse",
            ),
        )
        op.create_index("ix_fbs_stock_sources_user_id", "fbs_stock_sources", ["user_id"])

    if "product_fbs_stocks" not in tables:
        op.create_table(
            "product_fbs_stocks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("warehouse_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("stock", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "product_id",
                "warehouse_id",
                name="uq_product_fbs_stock_product_warehouse",
            ),
        )
        op.create_index("ix_product_fbs_stocks_user_id", "product_fbs_stocks", ["user_id"])
        op.create_index("ix_product_fbs_stocks_product_id", "product_fbs_stocks", ["product_id"])

    _migrate_legacy_settings(bind)


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "product_fbs_stocks" in tables:
        op.drop_index("ix_product_fbs_stocks_product_id", table_name="product_fbs_stocks")
        op.drop_index("ix_product_fbs_stocks_user_id", table_name="product_fbs_stocks")
        op.drop_table("product_fbs_stocks")

    if "fbs_stock_sources" in tables:
        op.drop_index("ix_fbs_stock_sources_user_id", table_name="fbs_stock_sources")
        op.drop_table("fbs_stock_sources")
