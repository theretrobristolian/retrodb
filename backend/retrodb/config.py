"""Runtime configuration loaded from environment variables."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str


def get_settings() -> Settings:
    database_url = os.getenv("RETRODB_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("RETRODB_DATABASE_URL is not configured")

    return Settings(
        environment=os.getenv("RETRODB_ENV", "production"),
        database_url=database_url,
    )
