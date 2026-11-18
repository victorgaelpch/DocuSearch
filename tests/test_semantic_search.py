"""Búsqueda semántica en el motor y en GET /search (DOC-14).

Usa ``HashingEncoder`` para no descargar el modelo; la prueba de paráfrasis
con el modelo real es opcional (marca ``semantic_model``).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("faiss")

from backend.app.cli import main as cli_main
from backend.app.config import Settings
from backend.app.documents.models import WIKIPEDIA_COLLECTION
from backend.app.main import create_app
from backend.app.nlp import embeddings
from backend.app.nlp.embeddings import EmbeddingUnavailableError, HashingEncoder
from backend.app.search import semantic_index

FIXTURES = Path(__file__).parent / "fixtures"
DOCS = {
    "volcanes.txt": "Los volcanes expulsan lava ceniza y gases durante una erupción violenta.",
    "fotosintesis.txt": "La fotosíntesis convierte luz solar en energía química dentro de las plantas.",
}


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(tmp_path / "data")


def _client(settings: Settings, factory=lambda: HashingEncoder(64)) -> TestClient:
    client = TestClient(create_app(settings, encoder_factory=factory))
    for name, text in DOCS.items():
        assert client.post("/documents", files={"file": (name, text.encode())}).status_code == 201
    pdf = (FIXTURES / "muestra.pdf").read_bytes()
    assert client.post("/documents", files={"file": ("muestra.pdf", pdf)}).status_code == 201
    return client


def test_semantic_search_returns_same_shape_as_bm25(settings: Settings, lexical_pipeline) -> None:
    client = _client(settings)
    semantic = client.get("/search", params={"q": "lava y ceniza de volcanes", "method": "semantic"})
    assert semantic.status_code == 200, semantic.text
    body = semantic.json()
    lexical = client.get("/search", params={"q": "lava y ceniza de volcanes"}).json()
    assert set(body) == set(lexical)
    assert set(body["results"][0]) == set(lexical["results"][0])
    top = body["results"][0]
    assert top["original_filename"] == "volcanes.txt" and top["method"] == "semantic"
    assert top["download_url"] == f"/documents/{top['doc_id']}/download"
    assert body["query_tokens"] == [] and body["index_version"]
    assert all(r["score"] > 0 for r in body["results"])
    assert [r["rank"] for r in body["results"]] == list(range(1, body["total"] + 1))
    assert client.get(top["download_url"]).status_code == 200


def test_semantic_hits_keep_page_provenance(settings: Settings, lexical_pipeline) -> None:
    client = _client(settings)
    results = client.get("/search", params={"q": "índice invertido", "method": "semantic", "k": 10}).json()["results"]
    pdf_hits = [r for r in results if r["original_filename"] == "muestra.pdf"]
    assert pdf_hits and all(r["page_start"] >= 1 and r["page"] == r["page_start"] for r in pdf_hits)


def test_semantic_k_and_determinism(settings: Settings, lexical_pipeline) -> None:
    client = _client(settings)
    params = {"q": "energía de plantas", "method": "semantic"}
    assert len(client.get("/search", params={**params, "k": 1}).json()["results"]) == 1
    first = client.get("/search", params={**params, "k": 10}).json()
    second = client.get("/search", params={**params, "k": 10}).json()
    assert [r["chunk_id"] for r in first["results"]] == [r["chunk_id"] for r in second["results"]]
    assert first["index_version"] == second["index_version"]


def test_new_upload_enters_semantic_index_incrementally(settings: Settings, lexical_pipeline) -> None:
    client = _client(settings)
    before = client.get("/search", params={"q": "astrolabio", "method": "semantic"}).json()
    client.post("/documents", files={"file": ("astro.txt", "El astrolabio medía la altura de los astros.".encode())})
    after = client.get("/search", params={"q": "astrolabio", "method": "semantic"}).json()
    assert after["index_version"] != before["index_version"]
    assert after["results"][0]["original_filename"] == "astro.txt"
    engine = client.app.state.search_engine
    report = engine.semantic.last_reports["user"]
    assert (report.added, report.kept) == (1, report.total - 1)


def test_needs_ocr_documents_are_not_indexed(settings: Settings, lexical_pipeline) -> None:
    import pymupdf

    client = _client(settings)
    blank = pymupdf.open()
    blank.new_page()
    response = client.post("/documents", files={"file": ("escaneado.pdf", blank.tobytes())})
    assert response.json()["extraction_status"] == "needs_ocr"
    results = client.get("/search", params={"q": "documento escaneado", "method": "semantic", "k": 100}).json()["results"]
    assert all(r["original_filename"] != "escaneado.pdf" for r in results)


def test_collections_stay_separate(settings: Settings, lexical_pipeline) -> None:
    client = _client(settings)
    wiki = client.get("/search", params={"q": "volcanes", "method": "semantic", "collection": "wikipedia_es"}).json()
    assert wiki["total"] == 0 and wiki["collection"] == WIKIPEDIA_COLLECTION


def test_semantic_unavailable_returns_503_and_lexical_still_works(settings: Settings, lexical_pipeline) -> None:
    def missing():
        raise EmbeddingUnavailableError("Falta el extra 'semantic'")

    client = _client(settings, factory=missing)
    response = client.get("/search", params={"q": "volcanes", "method": "semantic"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "semantic_unavailable"
    assert client.get("/search", params={"q": "volcanes"}).json()["total"] >= 1


def test_index_info_reports_semantic_without_building(settings: Settings, lexical_pipeline) -> None:
    client = _client(settings)
    semantic = next(i for i in client.get("/search/index").json()["indexes"] if i["method"] == "semantic")
    assert semantic["loaded"] is False and "available" in semantic
    client.get("/search", params={"q": "volcanes", "method": "semantic"})
    semantic = next(i for i in client.get("/search/index").json()["indexes"] if i["method"] == "semantic")
    assert semantic["loaded"] is True and semantic["chunks"] == 3 and semantic["metric"] == "cosine"


def test_reindex_cli_with_semantic(settings: Settings, monkeypatch, capsys, lexical_pipeline) -> None:
    import json

    _client(settings)
    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(settings.paths.root))
    monkeypatch.setattr(embeddings, "get_encoder", lambda: HashingEncoder(64))
    assert cli_main(["reindex", "--collection", "user", "--semantic"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["semantic"][0]["reason"] == "forced" and report["semantic"][0]["total"] == 3
    assert (settings.paths.indexes_dir / "semantic" / "user" / "index.faiss").is_file()

    def no_faiss():
        raise EmbeddingUnavailableError("Falta faiss-cpu (extra 'semantic')")

    monkeypatch.setattr(semantic_index, "_faiss", no_faiss)
    assert cli_main(["reindex", "--collection", "user", "--semantic"]) == 1


@pytest.mark.semantic_model
@pytest.mark.skipif(
    not (embeddings.semantic_available() and os.environ.get("DOCUSEARCH_TEST_SEMANTIC_MODEL") == "1"),
    reason="requiere el extra semantic y DOCUSEARCH_TEST_SEMANTIC_MODEL=1",
)
def test_real_model_finds_paraphrase_without_shared_words(settings: Settings, lexical_pipeline) -> None:
    client = TestClient(create_app(settings))
    texts = {
        "dengue.txt": "El dengue es una enfermedad viral transmitida por la picadura de mosquitos Aedes.",
        "fotosintesis.txt": DOCS["fotosintesis.txt"],
        "volcanes.txt": DOCS["volcanes.txt"],
    }
    for name, text in texts.items():
        client.post("/documents", files={"file": (name, text.encode())})
    query = "infección que contagian los zancudos"
    assert client.get("/search", params={"q": query}).json()["total"] == 0  # BM25 no comparte palabras
    top = client.get("/search", params={"q": query, "method": "semantic"}).json()["results"][0]
    assert top["original_filename"] == "dengue.txt"
