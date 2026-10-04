"""Core RetroDB relational models."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Platform(TimestampMixin, Base):
    __tablename__ = "platform"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(160))
    generation: Mapped[int | None] = mapped_column(SmallInteger)
    release_date: Mapped[date | None] = mapped_column(Date)


class Company(TimestampMixin, Base):
    __tablename__ = "company"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)


class Region(Base):
    __tablename__ = "region"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class Language(Base):
    __tablename__ = "language"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class Game(TimestampMixin, Base):
    __tablename__ = "game"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_title: Mapped[str] = mapped_column(String(255), nullable=False)
    synopsis: Mapped[str | None] = mapped_column(Text)
    primary_developer_id: Mapped[int | None] = mapped_column(
        ForeignKey("company.id", ondelete="SET NULL")
    )

    __table_args__ = (Index("ix_game_sort_title", "sort_title"),)


class Release(TimestampMixin, Base):
    __tablename__ = "release"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), nullable=False
    )
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platform.id", ondelete="RESTRICT"), nullable=False
    )
    region_id: Mapped[int | None] = mapped_column(
        ForeignKey("region.id", ondelete="SET NULL")
    )
    publisher_id: Mapped[int | None] = mapped_column(
        ForeignKey("company.id", ondelete="SET NULL")
    )
    title_override: Mapped[str | None] = mapped_column(String(255))
    edition: Mapped[str | None] = mapped_column(String(160))
    release_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_release_game", "game_id"),
        Index("ix_release_platform", "platform_id"),
        Index("ix_release_region", "region_id"),
    )


class ReleaseLanguage(Base):
    __tablename__ = "release_language"

    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), primary_key=True
    )
    language_id: Mapped[int] = mapped_column(
        ForeignKey("language.id", ondelete="RESTRICT"), primary_key=True
    )


class Media(TimestampMixin, Base):
    __tablename__ = "media"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False
    )
    disc_number: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    serial: Mapped[str | None] = mapped_column(String(100))
    product_code: Mapped[str | None] = mapped_column(String(100))
    crc32: Mapped[str | None] = mapped_column(String(8))
    md5: Mapped[str | None] = mapped_column(String(32))
    sha1: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("disc_number > 0", name="ck_media_disc_number_positive"),
        Index("ix_media_release", "release_id"),
        Index("ix_media_serial", "serial"),
        Index("ix_media_sha1", "sha1"),
    )


class ExternalProvider(TimestampMixin, Base):
    __tablename__ = "external_provider"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))


class ExternalReference(TimestampMixin, Base):
    __tablename__ = "external_reference"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("external_provider.id", ondelete="RESTRICT"), nullable=False
    )
    game_id: Mapped[int | None] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE")
    )
    release_id: Mapped[int | None] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE")
    )
    media_id: Mapped[int | None] = mapped_column(
        ForeignKey("media.id", ondelete="CASCADE")
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_url: Mapped[str | None] = mapped_column(String(1000))
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(game_id, release_id, media_id) = 1",
            name="ck_external_reference_one_entity",
        ),
        Index(
            "uq_external_reference_game",
            "provider_id",
            "external_id",
            "game_id",
            unique=True,
            postgresql_where=text("game_id IS NOT NULL"),
        ),
        Index(
            "uq_external_reference_release",
            "provider_id",
            "external_id",
            "release_id",
            unique=True,
            postgresql_where=text("release_id IS NOT NULL"),
        ),
        Index(
            "uq_external_reference_media",
            "provider_id",
            "external_id",
            "media_id",
            unique=True,
            postgresql_where=text("media_id IS NOT NULL"),
        ),
    )


class CollectionSource(TimestampMixin, Base):
    __tablename__ = "collection_source"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    root_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    read_only: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LibraryItem(TimestampMixin, Base):
    __tablename__ = "library_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("collection_source.id", ondelete="CASCADE"), nullable=False)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platform.id", ondelete="RESTRICT"), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(2000), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    extension: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_missing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ra_hash: Mapped[str | None] = mapped_column(String(32))
    ra_game_id: Mapped[int | None] = mapped_column(BigInteger)
    ra_game_title: Mapped[str | None] = mapped_column(String(500))
    ra_match_status: Mapped[str | None] = mapped_column(String(32))
    ra_hash_error: Mapped[str | None] = mapped_column(String(500))
    ra_hashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("source_id", "relative_path", name="uq_library_item_source_path"),
        Index("ix_library_item_platform", "platform_id"),
        Index("ix_library_item_missing", "is_missing"),
        Index("ix_library_item_filename", "filename"),
        Index("ix_library_item_ra_hash", "ra_hash"),
        Index("ix_library_item_ra_status", "ra_match_status"),
    )
