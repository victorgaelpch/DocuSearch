"""Pruebas de extremo a extremo de v0.2: búsqueda semántica e híbrida (DOC-17).

Recorren el flujo completo con la API real y un codificador determinista
(``HashingEncoder``), sin descargar el modelo: carga → fragmentación →
índice FAISS → búsqueda ``semantic``/``hybrid`` → documento, página y
original. La prueba con el modelo real está en ``test_semantic_search.py``
(marca ``semantic_model``).
"""

from __future__ import annotations

import random
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("faiss")

from backend.app.cli import main as cli_main  # noqa: E402
from backend.app.config import Settings  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.nlp import embeddings  # noqa: E402
from backend.app.nlp.embeddings import EmbeddingUnavailableError, HashingEncoder  # noqa: E402
from backend.app.search.evaluation import benchmark_latency  # noqa: E402
from tests.auth_helpers import admin_client

FILLER = "La biblioteca municipal organiza talleres de lectura para estudiantes y vecinos".split()


class CountingEncoder(HashingEncoder):
    def __init__(self) -> None:
        super().__init__(64)
        self.calls = 0

    def encode(self, texts):
        self.calls += len(texts)
        return super().encode(texts)


def _filler(n: int, seed: int) -> str:
    rng = random.Random(seed)
    return " ".join(rng.choice(FILLER) for _ in range(n))


def _pdf(pages: list[str]) -> bytes:
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        words = text.split()
        lines = [" ".join(words[i : i + 10]) for i in range(0, len(words), 10)]
        page.insert_textbox(pymupdf.Rect(36, 36, 560, 806), "\n".join(lines), fontsize=7)
    data = document.tobytes()
    document.close()
    return data


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(tmp_path / "data")


@pytest.mark.parametrize("method", ["semantic", "hybrid"])
def test_full_flow_page_provenance(settings: Settings, method: str, lexical_pipeline) -> None:
    client = admin_client(settings, encoder_factory=lambda: HashingEncoder(64))
    pages = [_filler(180, 1), _filler(180, 2), _filler(90, 3) + " xilófono marimba percusión " + _filler(90, 4)]
    doc_id = client.post("/documents", files={"file": ("informe.pdf", _pdf(pages))}).json()["doc_id"]
    client.post("/documents", files={"file": ("otro.txt", "El café se cultiva en montañas tropicales.".encode())})
    results = client.get("/search", params={"q": "xilófono marimba percusión", "method": method}).json()["results"]
    top = results[0]
    assert top["doc_id"] == doc_id and top["page_start"] <= 3 <= top["page_end"]
    chunk = client.get(f"/documents/{doc_id}/chunks").json()["items"]
    assert "xilófono" in next(c for c in chunk if c["chunk_id"] == top["chunk_id"])["text"]
    download = client.get(top["download_url"])
    assert download.status_code == 200 and download.content.startswith(b"%PDF")


def test_restart_reuses_faiss_index_without_reencoding(settings: Settings, lexical_pipeline) -> None:
    first_encoder = CountingEncoder()
    first = admin_client(settings, encoder_factory=lambda: first_encoder)
    for i in range(5):
        first.post("/documents", files={"file": (f"d{i}.txt", (_filler(300, i) + f" clave{i}").encode())})
    before = first.get("/search", params={"q": "clave3", "method": "hybrid"}).json()
    assert first_encoder.calls > 0

    second_encoder = CountingEncoder()
    restarted = admin_client(settings, encoder_factory=lambda: second_encoder)
    after = restarted.get("/search", params={"q": "clave3", "method": "hybrid"}).json()
    assert second_encoder.calls == 1  # solo la consulta: los fragmentos se leen del disco
    assert after["index_version"] == before["index_version"]
    assert [r["chunk_id"] for r in after["results"]] == [r["chunk_id"] for r in before["results"]]


def test_service_without_semantic_extra_keeps_v01_flow(settings: Settings, lexical_pipeline) -> None:
    def missing():
        raise EmbeddingUnavailableError("Falta el extra 'semantic'")

    client = admin_client(settings, encoder_factory=missing)
    upload = client.post("/documents", files={"file": ("nota.txt", "Los volcanes expulsan lava.".encode())})
    assert upload.status_code == 201
    assert client.get("/search", params={"q": "volcanes"}).json()["total"] == 1
    for method in ("semantic", "hybrid"):
        assert client.get("/search", params={"q": "volcanes", "method": method}).status_code == 503
    info = client.get("/search/index").json()
    assert any(i["method"] == "semantic" and i["loaded"] is False for i in info["indexes"])
    assert client.get("/health").json() == {"status": "ok"}


def test_latency_all_methods_under_two_seconds(settings: Settings, lexical_pipeline) -> None:
    """RNF de tiempo de respuesta con ~150 fragmentos sintéticos (no sustituye a la medición real)."""
    client = admin_client(settings, encoder_factory=lambda: HashingEncoder(64))
    for i in range(30):
        client.post("/documents", files={"file": (f"doc_{i}.txt", (_filler(900, 100 + i) + f" termino{i}").encode())})
    client.get("/search", params={"q": "biblioteca"})
    engine = client.app.state.search_engine
    report = benchmark_latency(
        engine, ["talleres de lectura", "termino7"], methods=("bm25", "semantic", "hybrid"), collection="user", repeats=2
    )
    assert all(m["under_2s"] for m in report["methods"].values()), report
    assert report["semantic_load_ms"] is not None
    if report["memory_mb"] is not None:
        assert report["memory_mb"]["after"] > 0


def test_cli_benchmark_semantic_methods(settings: Settings, monkeypatch, capsys, tmp_path: Path, lexical_pipeline) -> None:
    import json

    from backend.app.documents.service import DocumentService

    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(settings.paths.root))
    service = DocumentService(Settings.from_env())
    service.ingest_corpus_text(collection="wikipedia_es", title="Oro", text="El oro es un metal precioso. " * 5, filename="1.txt")
    queries = tmp_path / "q.json"
    queries.write_text(json.dumps({"queries": [{"id": "q", "query": "metal precioso", "relevant": ["Oro"]}]}), encoding="utf-8")
    monkeypatch.setattr(embeddings, "get_encoder", lambda: HashingEncoder(64))
    assert cli_main(["benchmark", "--queries", str(queries), "--repeats", "1", "--methods", "semantic", "hybrid"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report["methods"]) == {"semantic", "hybrid"}

    def missing():
        raise EmbeddingUnavailableError("Falta el extra 'semantic'")

    monkeypatch.setattr(embeddings, "get_encoder", missing)
    assert cli_main(["benchmark", "--queries", str(queries), "--repeats", "1", "--methods", "semantic"]) == 1
