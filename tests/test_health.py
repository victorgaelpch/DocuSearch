"""Smoke tests for the baseline FastAPI service (DOC-01)."""

from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_returns_ok() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_is_exposed() -> None:
    response = TestClient(app).get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "DocuSearch AI"
