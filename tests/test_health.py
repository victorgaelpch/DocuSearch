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


def test_version_matches_pyproject() -> None:
    import re
    from pathlib import Path

    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    expected = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE).group(1)
    body = TestClient(app).get("/version").json()
    assert body == {"name": "DocuSearch AI", "version": expected}
    assert TestClient(app).get("/openapi.json").json()["info"]["version"] == expected
