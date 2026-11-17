"""Pruebas de integración de GET /search y del comando reindex (DOC-10)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.cli import main as cli_main
from backend.app.config import Settings
from backend.app.documents.models import WIKIPEDIA_COLLECTION
from backend.app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(tmp_path / "data")


@pytest.fixture()
def client(settings: Settings, lexical_pipeline) -> TestClient:
    client = TestClient(create_app(settings))
    for name in ("muestra.pdf", "muestra.docx", "muestra.txt"):
        response = client.post("/documents", files={"file": (name, (FIXTURES / name).read_bytes())})
        assert response.status_code == 201
    return client


def _search(client: TestClient, **params):
    return client.get("/search", params=params)


@pytest.mark.parametrize(
    ("query", "filename"),
    [
        ("índice invertido", "muestra.pdf"),
        ("lematización forma base", "muestra.docx"),
        ("embeddings significado oraciones", "muestra.txt"),
    ],
)
def test_search_retrieves_text_from_pdf_docx_and_txt(client: TestClient, query: str, filename: str) -> None:
    body = _search(client, q=query).json()
    assert body["method"] == "bm25" and body["k"] == 10 and body["collection"] == "user"
    top = body["results"][0]
    assert top["original_filename"] == filename
    assert set(top) >= {"doc_id", "chunk_id", "title", "snippet", "page", "score", "rank", "download_url"}
    assert top["rank"] == 1


def test_result_points_to_document_page_and_original(client: TestClient) -> None:
    top = _search(client, q="pingüino cañón").json()["results"][0]
    assert top["original_filename"] == "muestra.pdf"
    assert (top["page_start"], top["page_end"]) == (1, 2)
    detail = client.get(f"/documents/{top['doc_id']}").json()
    assert detail["title"] == top["title"]
    chunks = client.get(f"/documents/{top['doc_id']}/chunks").json()["items"]
    assert top["chunk_id"] in {c["chunk_id"] for c in chunks}
    download = client.get(top["download_url"])
    assert download.status_code == 200 and download.content == (FIXTURES / "muestra.pdf").read_bytes()


def test_tfidf_method_and_k(client: TestClient) -> None:
    body = _search(client, q="búsqueda", method="tfidf", k=1).json()
    assert body["method"] == "tfidf" and body["k"] == 1 and len(body["results"]) == 1
    assert len(_search(client, q="búsqueda", k=10).json()["results"]) == 3


def test_order_is_deterministic_for_same_index_version(client: TestClient) -> None:
    first = _search(client, q="búsqueda documentos").json()
    second = _search(client, q="búsqueda documentos").json()
    assert first["index_version"] == second["index_version"]
    key = lambda body: [(r["chunk_id"], r["score"], r["rank"]) for r in body["results"]]  # noqa: E731
    assert key(first) == key(second)
    scores = [r["score"] for r in first["results"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"q": ""}, None),
        ({"q": "   "}, "empty_query"),
        ({"q": "x", "k": 0}, None),
        ({"q": "x", "k": 101}, None),
        ({"q": "x", "k": "diez"}, None),
        ({"q": "x", "method": "semantic"}, None),
        ({"q": "x", "collection": "privada"}, None),
        ({"q": "a" * 501}, None),
        ({"q": "�ndice"}, "invalid_encoding"),
        ({}, None),
    ],
)
def test_invalid_parameters_return_clear_422(client: TestClient, params: dict, code) -> None:
    response = _search(client, **params)
    assert response.status_code == 422
    body = response.json()
    if code:
        assert body["error"]["code"] == code
    else:
        assert body["detail"]  # validación estándar de FastAPI con el campo afectado


@pytest.mark.parametrize("query", ["el de la que", "xyzzy quásar zigurat", "¿?!"])
def test_queries_without_results(client: TestClient, query: str) -> None:
    response = _search(client, q=query)
    assert response.status_code == 200
    assert response.json()["total"] == 0 and response.json()["results"] == []


def test_search_on_empty_collection(settings: Settings, lexical_pipeline) -> None:
    client = TestClient(create_app(settings))
    body = client.get("/search", params={"q": "gato"}).json()
    assert body["total"] == 0
    assert client.get("/search", params={"q": "gato", "collection": WIKIPEDIA_COLLECTION}).json()["total"] == 0


def test_new_upload_is_searchable_and_changes_index_version(client: TestClient) -> None:
    before = _search(client, q="astrolabio").json()
    assert before["total"] == 0
    client.post("/documents", files={"file": ("astro.txt", "El astrolabio medía la altura de los astros.".encode())})
    after = _search(client, q="astrolabio").json()
    assert after["total"] == 1 and after["index_version"] != before["index_version"]


def test_index_info_exposes_parameters(client: TestClient) -> None:
    info = client.get("/search/index").json()
    assert info["chunks"] == 3
    methods = {i["method"]: i["params"] for i in info["indexes"]}
    assert methods["bm25"]["k1"] == 1.5 and methods["tfidf"]["norm"] == "l2"
    assert info["lexical_pipeline"]["pipeline"] == "lexical"


def test_openapi_documents_search(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    params = {p["name"] for p in spec["paths"]["/search"]["get"]["parameters"]}
    assert params == {"q", "method", "k", "collection"}


def test_cli_reindex(client: TestClient, settings: Settings, monkeypatch, capsys) -> None:
    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(settings.paths.root))
    assert cli_main(["reindex", "--collection", "user"]) == 0
    output = capsys.readouterr().out
    assert '"documents": 3' in output and '"method": "bm25"' in output
    # el servidor sigue respondiendo con los mismos resultados tras reindexar
    assert _search(client, q="índice invertido").json()["results"][0]["original_filename"] == "muestra.pdf"
