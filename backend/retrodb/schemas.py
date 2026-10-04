"""Public API response schemas."""

from datetime import date

from pydantic import BaseModel, ConfigDict


class PlatformRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    manufacturer: str | None
    generation: int | None
    release_date: date | None
