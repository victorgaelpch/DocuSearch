"""Edición y eliminación de documentos con consistencia de índices (DOC-30)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.documents.repository import DocumentRepository
from backend.app.nlp.embeddings import HashingEncoder
from tests.auth_helpers import admin_client, anonymous_client, logged_client

FIXTURES = Path(__file__).parent / "fixtures"
pytest.importorskip("faiss")


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(tmp_path / "data")


@pytest.fixture()
def client(settings: Settings, lexical_pipeline):
    return admin_client(settings, encoder_factory=lambda: HashingEncoder(64))


def _upload(client, name: str, data: bytes | None = None) -> dict:
    response = client.post("/documents", files={"file": (name, data if data is not None else (FIXTURES / name).read_bytes())})
    assert response.status_code == 201, response.text
    return response.json()


def _delete(client, doc_id: str, confirm: str | None = None):
    return client.delete(f"/documents/{doc_id}", params={"confirm": confirm if confirm is not None else doc_id})


# -- edición -------------------------------------------------------------------

def test_rename_keeps_hash_original_and_chunks(client, settings: Settings) -> None:
    doc = _upload(client, "muestra.pdf")
    chunks_before = client.get(f"/documents/{doc['doc_id']}/chunks").json()["items"]
    original = client.get(f"/documents/{doc['doc_id']}/download").content
    response = client.patch(f"/documents/{doc['doc_id']}", json={"title": "  Informe   renombrado ", "description": "Resumen", "tags": ["pln", "pln", " prueba "]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Informe renombrado"
    assert body["sha256"] == doc["sha256"] and body["doc_id"] == doc["doc_id"]
    assert body["metadata"]["description"] == "Resumen" and body["metadata"]["tags"] == ["pln", "prueba"]
    assert body["metadata"]["chunking"] == doc["metadata"]["chunking"]  # metadatos del sistema intactos
    assert client.get(f"/documents/{doc['doc_id']}/download").content == original
    assert client.get(f"/documents/{doc['doc_id']}/chunks").json()["items"] == chunks_before
    hit = client.get("/search", params={"q": "índice invertido"}).json()["results"][0]
    assert hit["title"] == "Informe renombrado" and hit["chunk_id"] == chunks_before[0]["chunk_id"]


@pytest.mark.parametrize(
    "payload",
    [{"title": ""}, {"title": "   "}, {"title": "x" * 501}, {"tags": ["a"] * 21}, {"tags": ["x" * 41]},
     {"description": "x" * 2001}, {"chunking": {"chunk_size": 1}}, {"sha256": "0" * 64}],
)
def test_invalid_edits_are_rejected(client, payload) -> None:
    doc = _upload(client, "muestra.txt")
    response = client.patch(f"/documents/{doc['doc_id']}", json=payload)
    assert response.status_code == 422, payload
    assert client.get(f"/documents/{doc['doc_id']}").json()["title"] == doc["title"]


def test_only_admin_with_csrf_can_edit(settings: Settings, client) -> None:
    doc = _upload(client, "muestra.txt")
    reader = logged_client(settings, role="user")
    assert reader.patch(f"/documents/{doc['doc_id']}", json={"title": "x"}).status_code == 403
    assert anonymous_client(settings).patch(f"/documents/{doc['doc_id']}", json={"title": "x"}).status_code == 401
    client.csrf_token, token = None, client.csrf_token
    assert client.patch(f"/documents/{doc['doc_id']}", json={"title": "x"}).status_code == 403


# -- eliminación -------------------------------------------------------------

def test_delete_removes_document_everywhere(client, settings: Settings) -> None:
    keep = _upload(client, "muestra.docx")
    doc = _upload(client, "muestra.pdf")
    chunk_ids = [c["chunk_id"] for c in client.get(f"/documents/{doc['doc_id']}/chunks").json()["items"]]
    # construir los índices léxico y semántico antes de borrar
    assert client.get("/search", params={"q": "índice invertido"}).json()["results"][0]["doc_id"] == doc["doc_id"]
    semantic_before = client.get("/search", params={"q": "índice invertido", "method": "semantic", "k": 50}).json()
    assert doc["doc_id"] in {r["doc_id"] for r in semantic_before["results"]}
    indexes = settings.paths.indexes_dir
    meta_path = indexes / "semantic" / "user" / "meta.json"
    assert {e["chunk_id"] for e in json.loads(meta_path.read_text())["entries"]} >= set(chunk_ids)
    original = settings.paths.originals_dir / DocumentRepository(settings.paths.metadata_db).get_document(doc["doc_id"]).storage_path

    response = _delete(client, doc["doc_id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted"] and body["original_removed"] and body["chunks_removed"] == len(chunk_ids)
    assert body["indexes"]["semantic"] == "purged"

    assert client.get(f"/documents/{doc['doc_id']}").status_code == 404
    assert client.get(f"/documents/{doc['doc_id']}/download").status_code == 404
    assert [d["doc_id"] for d in client.get("/documents").json()["items"]] == [keep["doc_id"]]
    for method in ("bm25", "tfidf", "semantic", "hybrid"):
        results = client.get("/search", params={"q": "índice invertido informe", "method": method, "k": 50}).json()["results"]
        assert doc["doc_id"] not in {r["doc_id"] for r in results}, method
    assert not original.exists()
    assert not list(original.parent.glob(".deleting-*"))
    # datos derivados purgados en disco
    cache = json.loads((indexes / "lexical_tokens.json").read_text())["entries"]
    assert not set(chunk_ids) & set(cache)
    remaining = {e["chunk_id"] for e in json.loads(meta_path.read_text())["entries"]}
    assert not set(chunk_ids) & remaining and remaining
    # el otro documento sigue disponible y se puede volver a cargar el borrado
    assert client.get("/search", params={"q": "lematización"}).json()["results"][0]["doc_id"] == keep["doc_id"]
    assert _upload(client, "muestra.pdf")["doc_id"] == doc["doc_id"]


def test_delete_requires_explicit_confirmation(client) -> None:
    doc = _upload(client, "muestra.txt")
    assert client.delete(f"/documents/{doc['doc_id']}").status_code == 422
    response = _delete(client, doc["doc_id"], confirm="doc_ffffffffffffffffffffffff")
    assert response.status_code == 400 and response.json()["error"]["code"] == "confirmation_required"
    assert client.get(f"/documents/{doc['doc_id']}").status_code == 200


def test_delete_permissions(settings: Settings, client) -> None:
    doc = _upload(client, "muestra.txt")
    assert _delete(logged_client(settings, role="user"), doc["doc_id"]).status_code == 403
    assert _delete(anonymous_client(settings), doc["doc_id"]).status_code == 401
    client.csrf_token = None
    assert _delete(client, doc["doc_id"]).status_code == 403
    assert DocumentRepository(settings.paths.metadata_db).get_document_or_none(doc["doc_id"]) is not None


def test_delete_unknown_and_corpus_documents(client, settings: Settings) -> None:
    assert _delete(client, "doc_000000000000000000000000").status_code == 404
    from backend.app.documents.service import DocumentService

    corpus = DocumentService(settings).ingest_corpus_text(
        collection="wikipedia_es", title="Volcán", text="Un volcán expulsa lava.", filename="volcan.txt"
    )
    assert _delete(client, corpus.document.doc_id).status_code == 404
    assert client.patch(f"/documents/{corpus.document.doc_id}", json={"title": "x"}).status_code == 404


def test_failed_metadata_delete_restores_original(client, settings: Settings, monkeypatch) -> None:
    doc = _upload(client, "muestra.txt")
    service = client.app.state.document_service

    def broken(doc_id: str) -> None:
        raise RuntimeError("disco lleno")

    monkeypatch.setattr(service.repository, "delete_document", broken)
    with pytest.raises(RuntimeError):
        _delete(client, doc["doc_id"])
    monkeypatch.undo()
    assert client.get(f"/documents/{doc['doc_id']}").status_code == 200
    assert client.get(f"/documents/{doc['doc_id']}/download").status_code == 200
    original_dir = settings.paths.originals_dir
    assert not list(original_dir.rglob(".deleting-*"))


def test_original_that_cannot_be_removed_is_reported(client, monkeypatch) -> None:
    doc = _upload(client, "muestra.txt")
    service = client.app.state.document_service
    monkeypatch.setattr(service.store, "discard", lambda staged: False)
    body = _delete(client, doc["doc_id"]).json()
    assert body["deleted"] is True and body["original_removed"] is False


def test_corrupt_semantic_index_is_dropped_not_kept(client, settings: Settings) -> None:
    doc = _upload(client, "muestra.pdf")
    client.get("/search", params={"q": "índice", "method": "semantic"})
    index_file = settings.paths.indexes_dir / "semantic" / "user" / "index.faiss"
    index_file.write_bytes(b"corrupto")
    body = _delete(client, doc["doc_id"]).json()
    assert body["indexes"]["semantic"] == "dropped"
    assert not index_file.exists()
