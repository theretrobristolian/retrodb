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
