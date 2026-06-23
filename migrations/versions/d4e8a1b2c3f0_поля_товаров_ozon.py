"""Поля товаров Ozon

Revision ID: d4e8a1b2c3f0
Revises: b2a8e1f04c31
Create Date: 2026-05-15 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "d4e8a1b2c3f0"
down_revision = "b2a8e1f04c31"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("products")}

    with op.batch_alter_table("products", schema=None) as batch_op:
        if "offer_id" not in columns:
            batch_op.add_column(sa.Column("offer_id", sa.String(length=128), nullable=True))
        if "barcode" not in columns:
            batch_op.add_column(sa.Column("barcode", sa.String(length=128), nullable=True))
        if "thumbnail_url" not in columns:
            batch_op.add_column(sa.Column("thumbnail_url", sa.String(length=512), nullable=True))
        if "sku" not in columns:
            batch_op.add_column(sa.Column("sku", sa.String(length=64), nullable=True))
        if "raw_data" not in columns:
            batch_op.add_column(sa.Column("raw_data", sa.JSON(), nullable=True))

    op.execute("UPDATE products SET offer_id = '' WHERE offer_id IS NULL")

    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.alter_column("offer_id", existing_type=sa.String(128), nullable=False)

    indexes = {idx["name"] for idx in insp.get_indexes("products")}
    if "uq_products_user_ozon" not in indexes:
        with op.batch_alter_table("products", schema=None) as batch_op:
            batch_op.create_unique_constraint(
                "uq_products_user_ozon", ["user_id", "ozon_product_id"]
            )
    if "ix_products_user_offer" not in indexes:
        with op.batch_alter_table("products", schema=None) as batch_op:
            batch_op.create_index("ix_products_user_offer", ["user_id", "offer_id"])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    indexes = {idx["name"] for idx in insp.get_indexes("products")}

    with op.batch_alter_table("products", schema=None) as batch_op:
        if "ix_products_user_offer" in indexes:
            batch_op.drop_index("ix_products_user_offer")
        if "uq_products_user_ozon" in indexes:
            batch_op.drop_constraint("uq_products_user_ozon", type_="unique")

    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.drop_column("raw_data")
        batch_op.drop_column("sku")
        batch_op.drop_column("thumbnail_url")
        batch_op.drop_column("barcode")
        batch_op.drop_column("offer_id")
