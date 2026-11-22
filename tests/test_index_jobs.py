"""Panel de índices y tareas de reindexación con estado real (DOC-31)."""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.jobs import JobKind, JobManager, JobStatus
from backend.app.nlp.embeddings import EmbeddingUnavailableError, HashingEncoder
from tests.auth_helpers import admin_client, anonymous_client, logged_client

FIXTURES = Path(__file__).parent / "fixtures"
pytest.importorskip("faiss")


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(tmp_path / "data")


@pytest.fixture()
def client(settings: Settings, lexical_pipeline):
    client = admin_client(settings, encoder_factory=lambda: HashingEncoder(64))
    for name in ("muestra.pdf", "muestra.docx", "muestra.txt"):
        assert client.post("/documents", files={"file": (name, (FIXTURES / name).read_bytes())}).status_code == 201
    return client


def _start(client, kind: str, collection: str = "user"):
    return client.post(f"/admin/indexes/{collection}/jobs", json={"kind": kind})


def _wait(client, job_id: str, timeout: float = 30) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/admin/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("la tarea no terminó")


# -- gestor ---------------------------------------------------------------------

def test_manager_reports_only_real_states_and_progress() -> None:
    manager = JobManager()
    gate = threading.Event()
    seen: list[str] = []

    def work(ctx):
        ctx.progress(0, 2)
        gate.wait(5)
        ctx.progress(2, 2)
        return {"ok": True}

    job = manager.submit(JobKind.REINDEX, "user", work)
    for _ in range(100):
        snap = manager.snapshot(job.job_id)
        seen.append(snap["status"])
        if snap["status"] == "running" and snap["progress"]:
            break
        time.sleep(0.01)
    assert snap["status"] == "running" and snap["progress"] == {"done": 0, "total": 2}
    assert snap["result"] is None and snap["finished_at"] is None  # sin éxito anticipado
    gate.set()
    final = manager.wait(job.job_id)
    assert final["status"] == "succeeded" and final["result"] == {"ok": True} and final["duration_s"] >= 0


def test_manager_failure_and_one_job_per_collection() -> None:
    manager = JobManager()
    gate = threading.Event()
    first = manager.submit(JobKind.SEMANTIC, "user", lambda ctx: gate.wait(5) and {})
    with pytest.raises(Exception) as excinfo:
        manager.submit(JobKind.REINDEX, "user", lambda ctx: {})
    assert "user" in str(excinfo.value)
    other = manager.submit(JobKind.REINDEX, "wikipedia_es", lambda ctx: {})  # otra colección: en cola
    gate.set()
    manager.wait(first.job_id)
    failing = manager.submit(JobKind.OCR, "user", lambda ctx: (_ for _ in ()).throw(RuntimeError("sin disco")))
    result = manager.wait(failing.job_id)
    assert result["status"] == "failed" and "sin disco" in result["error"]
    assert manager.wait(other.job_id)["status"] == "succeeded"


# -- API --------------------------------------------------------------------------

def test_indexes_panel_reports_counts_versions_and_semantic(client) -> None:
    body = client.get("/admin/indexes").json()
    user = body["collections"][0]
    assert user["collection"] == "user"
    assert user["documents"] == 3 and user["chunks"] >= 3 and user["needs_ocr"] == 0
    assert user["lexical"]["version"] and set(user["lexical"]["methods"]) == {"bm25", "tfidf"}
    assert user["semantic"] == {"built": False}
    assert body["semantic_available"] is True and body["concurrent_jobs"] == 1
    assert body["embedding_model"]["name"].endswith("paraphrase-multilingual-MiniLM-L12-v2")


def test_reindex_job_runs_and_reports_result(client) -> None:
    before = client.get("/search/index").json()["index_version"]
    response = _start(client, "reindex")
    assert response.status_code == 202
    job = response.json()
    assert job["status"] in ("pending", "running") and job["result"] is None
    final = _wait(client, job["job_id"])
    assert final["status"] == "succeeded", final
    assert final["result"]["documents"] == 3 and final["result"]["failed"] == {}
    assert [st["step"] for st in final["steps"]] == ["Refragmentando desde los originales", "Reconstruyendo BM25 y TF-IDF"]
    assert final["steps"][0]["progress"] == {"done": 3, "total": 3}
    assert final["steps"][1]["progress"] is None  # sin medida real: no se inventa
    assert final["result"]["index_version"] == client.get("/search/index").json()["index_version"]
    assert before == final["result"]["index_version"]  # mismos datos → misma versión


def test_semantic_sync_then_panel_shows_index(client) -> None:
    final = _wait(client, _start(client, "semantic").json()["job_id"])
    assert final["status"] == "succeeded" and final["result"]["added"] >= 3
    semantic = client.get("/admin/indexes").json()["collections"][0]["semantic"]
    assert semantic["built"] and semantic["in_sync"] and semantic["pending_chunks"] == 0
    rebuilt = _wait(client, _start(client, "semantic_rebuild").json()["job_id"])
    assert rebuilt["status"] == "succeeded" and rebuilt["result"]["rebuilt"] is True


def test_semantic_job_fails_honestly_without_model(settings: Settings, lexical_pipeline) -> None:
    def missing():
        raise EmbeddingUnavailableError("Falta sentence-transformers (extra 'semantic')")

    client = admin_client(settings, encoder_factory=missing)
    final = _wait(client, _start(client, "semantic").json()["job_id"])
    assert final["status"] == "failed" and "sentence-transformers" in final["error"]


def test_reindex_failure_is_reported(client, settings: Settings) -> None:
    for path in settings.paths.originals_dir.rglob("*.txt"):
        path.unlink()
    final = _wait(client, _start(client, "reindex").json()["job_id"])
    assert final["status"] == "failed"
    assert len(final["result"]["failed"]) == 1 and final["result"]["documents"] == 2


def test_conflicting_job_returns_409(client, monkeypatch) -> None:
    gate = threading.Event()
    service = client.app.state.document_service
    original = service.rechunk

    def slow(collection=None, progress=None):
        gate.wait(5)
        return original(collection, progress)

    monkeypatch.setattr(service, "rechunk", slow)
    first = _start(client, "reindex").json()
    second = _start(client, "ocr")
    assert second.status_code == 409 and second.json()["error"]["code"] == "job_running"
    panel = client.get("/admin/indexes").json()["collections"][0]
    assert panel["active_job"]["job_id"] == first["job_id"] and panel["lexical"] is None
    # las búsquedas siguen funcionando durante la tarea
    assert client.get("/search", params={"q": "índice invertido"}).json()["total"] >= 1
    gate.set()
    assert _wait(client, first["job_id"])["status"] == "succeeded"


def test_ocr_job_without_pending_documents(client) -> None:
    final = _wait(client, _start(client, "ocr").json()["job_id"])
    assert final["status"] == "succeeded" and final["result"]["pending"] == 0


def test_validation_and_permissions(client, settings: Settings) -> None:
    assert _start(client, "borrar-todo").status_code == 422
    assert _start(client, "reindex", "no_existe").status_code == 404
    assert _start(client, "reindex", "../etc").status_code == 404
    assert client.get("/admin/jobs/abc").status_code == 422
    assert client.get("/admin/jobs/" + "0" * 32).status_code == 404
    reader = logged_client(settings, role="user")
    assert reader.get("/admin/indexes").status_code == 403
    assert _start(reader, "reindex").status_code == 403
    anon = anonymous_client(settings)
    assert anon.get("/admin/indexes").status_code == 401
    assert anon.get("/admin/jobs").status_code == 401
    client.csrf_token = None
    assert _start(client, "reindex").status_code == 403


def test_rechunk_with_new_config_changes_version(settings: Settings, lexical_pipeline, client) -> None:
    before = client.get("/search/index").json()["index_version"]
    small = admin_client(replace(settings, chunk_size=5, chunk_overlap=1), encoder_factory=lambda: HashingEncoder(64))
    final = _wait(small, _start(small, "reindex").json()["job_id"])
    assert final["status"] == "succeeded" and final["result"]["chunking"]["chunk_size"] == 5
    assert final["result"]["index_version"] != before


def test_panel_uses_one_consistent_job_snapshot(client, monkeypatch) -> None:
    """La tarea activa de la tarjeta sale de la misma instantánea que la lista (DOC-31)."""
    jobs = client.app.state.jobs if hasattr(client.app.state, "jobs") else None
    if jobs is None:
        client.get("/admin/indexes")
        jobs = client.app.state.jobs
    running = {"job_id": "a" * 32, "kind": "reindex", "collection": "user", "status": "running"}
    finished = {**running, "status": "succeeded"}
    calls = iter([[running], [finished]])
    monkeypatch.setattr(jobs, "recent", lambda limit=20: next(calls, [finished]))
    monkeypatch.setattr(jobs, "active", lambda collection: (_ for _ in ()).throw(AssertionError("no debe consultarse por separado")))
    body = client.get("/admin/indexes").json()
    card = body["collections"][0]
    assert card["active_job"]["job_id"] == body["recent_jobs"][0]["job_id"]
    assert card["active_job"]["status"] == body["recent_jobs"][0]["status"] == "running"
