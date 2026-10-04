"""Store RetroAchievements compatibility results.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-04
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("library_item", sa.Column("ra_hash", sa.String(32)))
    op.add_column("library_item", sa.Column("ra_game_id", sa.BigInteger()))
    op.add_column("library_item", sa.Column("ra_game_title", sa.String(500)))
    op.add_column("library_item", sa.Column("ra_match_status", sa.String(32)))
    op.add_column("library_item", sa.Column("ra_hash_error", sa.String(500)))
    op.add_column("library_item", sa.Column("ra_hashed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_library_item_ra_hash", "library_item", ["ra_hash"])
    op.create_index("ix_library_item_ra_status", "library_item", ["ra_match_status"])

def downgrade() -> None:
    op.drop_index("ix_library_item_ra_status", table_name="library_item")
    op.drop_index("ix_library_item_ra_hash", table_name="library_item")
    for name in ("ra_hashed_at", "ra_hash_error", "ra_match_status", "ra_game_title", "ra_game_id", "ra_hash"):
        op.drop_column("library_item", name)
