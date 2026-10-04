"""RetroDB HTTP application."""

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from retrodb import __version__
from retrodb.database import check_database, get_session
from retrodb.models import Platform
from retrodb.schemas import PlatformRead

app = FastAPI(
    title="RetroDB",
    description="Self-hosted retro-game collection catalogue",
    version=__version__,
    docs_url=None,
    redoc_url=None,
)


@app.get("/live")
def liveness() -> dict[str, str]:
    return {
        "status": "alive",
        "version": __version__,
    }


@app.get("/health")
def health() -> dict[str, str]:
    try:
        check_database()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc

    return {
        "status": "healthy",
        "database": "connected",
        "version": __version__,
    }


@app.get("/api/v1/platforms", response_model=list[PlatformRead])
def list_platforms(session: Session = Depends(get_session)) -> list[Platform]:
    statement = select(Platform).order_by(Platform.name)
    return list(session.scalars(statement))
