"""RetroDB HTTP application."""

from fastapi import FastAPI, HTTPException, status

from retrodb import __version__
from retrodb.database import check_database

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
