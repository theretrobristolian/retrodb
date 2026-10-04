"""Add read-only collection inventory.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("collection_source",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("root_path", sa.String(1000), nullable=False),
        sa.Column("read_only", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_collection_source_slug"))
    op.create_table("library_item",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source_id", sa.BigInteger(), sa.ForeignKey("collection_source.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform_id", sa.BigInteger(), sa.ForeignKey("platform.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("relative_path", sa.String(2000), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("extension", sa.String(32), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_missing", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_id", "relative_path", name="uq_library_item_source_path"))
    op.create_index("ix_library_item_platform", "library_item", ["platform_id"])
    op.create_index("ix_library_item_missing", "library_item", ["is_missing"])
    op.create_index("ix_library_item_filename", "library_item", ["filename"])

def downgrade() -> None:
    op.drop_table("library_item")
    op.drop_table("collection_source")
