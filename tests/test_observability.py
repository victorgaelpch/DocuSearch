"""Registros, identificador de petición, métricas y preparación (DOC-40)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.observability import JsonFormatter, Metrics, _percentile
from tests.auth_helpers import ADMIN_PASSWORD, admin_client, anonymous_client, logged_client

FIXTURES = Path(__file__).parent / "fixtures"


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(JsonFormatter().format(record))

    def events(self, name: str) -> list[dict]:
        return [json.loads(line) for line in self.lines if json.loads(line)["event"] == name]


@pytest.fixture()
def records():
    handler = _Records()
    logger = logging.getLogger("docusearch")
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(tmp_path / "data")


def test_every_response_has_request_id(settings: Settings) -> None:
    client = anonymous_client(settings)
    generated = client.get("/health").headers["x-request-id"]
    assert len(generated) == 16
    assert client.get("/health", headers={"X-Request-ID": "mi-peticion-123"}).headers["x-request-id"] == "mi-peticion-123"
    unsafe = client.get("/health", headers={"X-Request-ID": "<script>\nx"}).headers["x-request-id"]
    assert unsafe != "<script>\nx" and len(unsafe) == 16
    # también en rechazos del middleware de seguridad
    assert client.post("/documents", content=b"x", headers={"content-length": "1"}).headers["x-request-id"]


def test_logs_are_json_without_queries_bodies_or_passwords(settings: Settings, records) -> None:
    client = anonymous_client(settings)
    client.post("/auth/login", json={"username": "admin", "password": "una-clave-incorrecta-1"})
    client.login("admin", ADMIN_PASSWORD)
    client.post("/documents", files={"file": ("secreto.txt", "Contenido confidencial del expediente".encode())})
    client.get("/search", params={"q": "expediente confidencial"})
    text = "\n".join(records.lines)
    for secret in (ADMIN_PASSWORD, "una-clave-incorrecta-1", "expediente", "confidencial", "Contenido"):
        assert secret not in text, secret
    requests = records.events("request")
    assert {r["path"] for r in requests} >= {"/auth/login", "/documents", "/search"}
    assert all("?" not in r["path"] and r["duration_ms"] >= 0 and r["request_id"] for r in requests)
    search = records.events("search")[0]
    assert search["method"] == "bm25" and search["collection"] == "user" and "q" not in search


def test_document_ids_are_logged_as_route_templates(settings: Settings, records) -> None:
    client = admin_client(settings)
    doc = client.post("/documents", files={"file": ("muestra.txt", (FIXTURES / "muestra.txt").read_bytes())}).json()
    client.get(f"/documents/{doc['doc_id']}")
    paths = {r["path"] for r in records.events("request")}
    assert "/documents/{doc_id}" in paths and doc["doc_id"] not in "\n".join(records.lines)


def test_unhandled_error_is_logged_with_request_id(settings: Settings, records, monkeypatch) -> None:
    client = admin_client(settings)
    service = client.app.state.document_service if hasattr(client.app.state, "document_service") else None
    client.get("/documents")
    service = client.app.state.document_service
    monkeypatch.setattr(service, "list_documents", lambda **kw: (_ for _ in ()).throw(RuntimeError("ruta /secreta/expediente.db")))
    response = client.get("/documents")
    assert response.status_code == 500
    request_id = response.json()["error"]["request_id"]
    assert "secreta" not in response.text
    error = records.events("unhandled_error")[0]
    assert error["request_id"] == request_id and error["error"] == "RuntimeError" and error["path"] == "/documents"


def test_metrics_separate_cold_and_warm(settings: Settings, lexical_pipeline) -> None:
    client = admin_client(settings)
    client.post("/documents", files={"file": ("muestra.txt", (FIXTURES / "muestra.txt").read_bytes())})
    for _ in range(5):
        client.get("/search", params={"q": "embeddings"})
    body = client.get("/admin/metrics").json()
    bm25 = body["search"]["bm25"]
    assert len(bm25["cold"]) == 1 and bm25["warm"]["count"] == 4
    assert bm25["warm"]["p50_ms"] <= bm25["warm"]["p95_ms"] <= bm25["warm"]["max_ms"]
    assert bm25["over_budget"] is False and body["budget_ms"] == 2000.0
    assert body["memory_mb"] is None or body["memory_mb"] > 0
    assert logged_client(settings, role="user").get("/admin/metrics").status_code == 403


def test_metrics_object_and_percentiles() -> None:
    metrics = Metrics()
    assert metrics.record_search("bm25", "user", "v1", 50.0) is True
    for value in (10.0, 20.0, 30.0, 3000.0):
        assert metrics.record_search("bm25", "user", "v1", value) is False
    assert metrics.record_search("bm25", "user", "v2", 40.0) is True  # índice nuevo: en frío
    snap = metrics.snapshot()["search"]["bm25"]
    assert snap["warm"]["count"] == 4 and snap["over_budget"] is True
    assert _percentile([], 0.5) is None and _percentile([5.0], 0.95) == 5.0


def test_readiness(settings: Settings) -> None:
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    ready = admin_client(settings).get("/health/ready")
    assert ready.status_code == 200 and ready.json()["status"] == "ready"
    assert set(ready.json()["essential"]) == {"database", "data_dir_writable", "lexical_model", "admin_account"}
    assert set(ready.json()["optional"]) == {"semantic", "ocr", "rag_configured"}
    without_admin = TestClient(create_app(replace(settings, admin_password_hash=None)))
    response = without_admin.get("/health/ready")
    assert response.status_code == 503 and response.json()["essential"]["admin_account"] is False
    assert without_admin.get("/health").json() == {"status": "ok"}  # vida, independiente de la preparación


def test_performance_report_is_reproducible(lexical_pipeline) -> None:
    from backend.app.perf import format_report, run_report

    report = run_report(repeats=1, methods=["bm25"])
    assert report["corpus"] == {"documents": 4, "chunks": 4}
    assert {i["file"] for i in report["ingestion"]} >= {"ciclo-del-agua.pdf", "redes-neuronales.docx", "reciclaje-en-casa.txt"}
    bm25 = report["search"]["bm25"]
    assert bm25["warm_http"]["count"] == len(__import__("json").loads((Path(__file__).resolve().parents[1] / "demo" / "consultas.json").read_text(encoding="utf-8"))["lexicas"])
    assert bm25["cold_first_query_ms"] > 0 and report["within_2s"] is True
    assert report["machine"]["cpu_count"] and report["machine"]["gpu"] == "no usada"
    text = format_report(report)
    assert "Búsqueda en caliente < 2 s: sí" in text and "bm25" in text
