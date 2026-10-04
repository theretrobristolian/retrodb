"""Create the initial core catalogue schema.

Revision ID: 0001
Revises:
Create Date: 2026-10-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "platform",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("manufacturer", sa.String(length=160)),
        sa.Column("generation", sa.SmallInteger()),
        sa.Column("release_date", sa.Date()),
        *timestamp_columns(),
        sa.UniqueConstraint("slug", name="uq_platform_slug"),
        sa.UniqueConstraint("name", name="uq_platform_name"),
    )

    op.create_table(
        "company",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        *timestamp_columns(),
        sa.UniqueConstraint("slug", name="uq_company_slug"),
        sa.UniqueConstraint("name", name="uq_company_name"),
    )

    op.create_table(
        "region",
        sa.Column("id", sa.SmallInteger(), sa.Identity(), primary_key=True),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.UniqueConstraint("code", name="uq_region_code"),
        sa.UniqueConstraint("name", name="uq_region_name"),
    )

    op.create_table(
        "language",
        sa.Column("id", sa.SmallInteger(), sa.Identity(), primary_key=True),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.UniqueConstraint("code", name="uq_language_code"),
        sa.UniqueConstraint("name", name="uq_language_name"),
    )

    op.create_table(
        "external_provider",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("base_url", sa.String(length=500)),
        *timestamp_columns(),
        sa.UniqueConstraint("slug", name="uq_external_provider_slug"),
        sa.UniqueConstraint("name", name="uq_external_provider_name"),
    )

    op.create_table(
        "game",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("sort_title", sa.String(length=255), nullable=False),
        sa.Column("synopsis", sa.Text()),
        sa.Column(
            "primary_developer_id",
            sa.BigInteger(),
            sa.ForeignKey("company.id", ondelete="SET NULL"),
        ),
        *timestamp_columns(),
    )
    op.create_index("ix_game_sort_title", "game", ["sort_title"])

    op.create_table(
        "release",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "game_id",
            sa.BigInteger(),
            sa.ForeignKey("game.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "platform_id",
            sa.BigInteger(),
            sa.ForeignKey("platform.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "region_id",
            sa.SmallInteger(),
            sa.ForeignKey("region.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "publisher_id",
            sa.BigInteger(),
            sa.ForeignKey("company.id", ondelete="SET NULL"),
        ),
        sa.Column("title_override", sa.String(length=255)),
        sa.Column("edition", sa.String(length=160)),
        sa.Column("release_date", sa.Date()),
        sa.Column("notes", sa.Text()),
        *timestamp_columns(),
    )
    op.create_index("ix_release_game", "release", ["game_id"])
    op.create_index("ix_release_platform", "release", ["platform_id"])
    op.create_index("ix_release_region", "release", ["region_id"])

    op.create_table(
        "release_language",
        sa.Column(
            "release_id",
            sa.BigInteger(),
            sa.ForeignKey("release.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "language_id",
            sa.SmallInteger(),
            sa.ForeignKey("language.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )

    op.create_table(
        "media",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "release_id",
            sa.BigInteger(),
            sa.ForeignKey("release.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("disc_number", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("serial", sa.String(length=100)),
        sa.Column("product_code", sa.String(length=100)),
        sa.Column("crc32", sa.String(length=8)),
        sa.Column("md5", sa.String(length=32)),
        sa.Column("sha1", sa.String(length=40)),
        sa.Column("notes", sa.Text()),
        *timestamp_columns(),
        sa.CheckConstraint(
            "disc_number > 0", name="ck_media_disc_number_positive"
        ),
    )
    op.create_index("ix_media_release", "media", ["release_id"])
    op.create_index("ix_media_serial", "media", ["serial"])
    op.create_index("ix_media_sha1", "media", ["sha1"])

    op.create_table(
        "external_reference",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "provider_id",
            sa.BigInteger(),
            sa.ForeignKey("external_provider.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "game_id",
            sa.BigInteger(),
            sa.ForeignKey("game.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "release_id",
            sa.BigInteger(),
            sa.ForeignKey("release.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "media_id",
            sa.BigInteger(),
            sa.ForeignKey("media.id", ondelete="CASCADE"),
        ),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("external_url", sa.String(length=1000)),
        sa.Column("metadata_json", postgresql.JSONB()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        *timestamp_columns(),
        sa.CheckConstraint(
            "num_nonnulls(game_id, release_id, media_id) = 1",
            name="ck_external_reference_one_entity",
        ),
    )
    op.create_index(
        "uq_external_reference_game",
        "external_reference",
        ["provider_id", "external_id", "game_id"],
        unique=True,
        postgresql_where=sa.text("game_id IS NOT NULL"),
    )
    op.create_index(
        "uq_external_reference_release",
        "external_reference",
        ["provider_id", "external_id", "release_id"],
        unique=True,
        postgresql_where=sa.text("release_id IS NOT NULL"),
    )
    op.create_index(
        "uq_external_reference_media",
        "external_reference",
        ["provider_id", "external_id", "media_id"],
        unique=True,
        postgresql_where=sa.text("media_id IS NOT NULL"),
    )

    platform = sa.table(
        "platform",
        sa.column("slug", sa.String()),
        sa.column("name", sa.String()),
        sa.column("manufacturer", sa.String()),
        sa.column("generation", sa.SmallInteger()),
        sa.column("release_date", sa.Date()),
    )
    op.bulk_insert(
        platform,
        [
            {
                "slug": "playstation",
                "name": "Sony PlayStation",
                "manufacturer": "Sony Computer Entertainment",
                "generation": 5,
                "release_date": sa.text("'1994-12-03'"),
            },
            {
                "slug": "playstation-2",
                "name": "Sony PlayStation 2",
                "manufacturer": "Sony Computer Entertainment",
                "generation": 6,
                "release_date": sa.text("'2000-03-04'"),
            },
        ],
    )

    region = sa.table(
        "region",
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
    )
    op.bulk_insert(
        region,
        [
            {"code": "EU", "name": "Europe"},
            {"code": "GB", "name": "United Kingdom"},
            {"code": "JP", "name": "Japan"},
            {"code": "US", "name": "United States"},
        ],
    )

    language = sa.table(
        "language",
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
    )
    op.bulk_insert(
        language,
        [
            {"code": "en", "name": "English"},
            {"code": "ja", "name": "Japanese"},
        ],
    )

    provider = sa.table(
        "external_provider",
        sa.column("slug", sa.String()),
        sa.column("name", sa.String()),
        sa.column("base_url", sa.String()),
    )
    op.bulk_insert(
        provider,
        [
            {
                "slug": "retroachievements",
                "name": "RetroAchievements",
                "base_url": "https://retroachievements.org",
            },
            {
                "slug": "redump",
                "name": "Redump",
                "base_url": "http://redump.org",
            },
            {
                "slug": "no-intro",
                "name": "No-Intro",
                "base_url": "https://no-intro.org",
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("external_reference")
    op.drop_table("media")
    op.drop_table("release_language")
    op.drop_table("release")
    op.drop_table("game")
    op.drop_table("external_provider")
    op.drop_table("language")
    op.drop_table("region")
    op.drop_table("company")
    op.drop_table("platform")
