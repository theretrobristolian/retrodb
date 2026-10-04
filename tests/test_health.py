"""Tests for the first application endpoints."""

from fastapi.testclient import TestClient

from retrodb.main import app

client = TestClient(app)


def test_liveness() -> None:
    response = client.get("/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "alive",
        "version": "0.1.0",
    }


def test_core_model_tables_are_registered() -> None:
    from retrodb.models import Base

    assert set(Base.metadata.tables) == {
        "company",
        "external_provider",
        "external_reference",
        "game",
        "language",
        "media",
        "platform",
        "region",
        "release",
        "release_language",
    }
