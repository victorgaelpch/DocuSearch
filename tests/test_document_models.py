"""Pruebas unitarias de los contratos Document y Chunk (DOC-02)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.documents import (
    WIKIPEDIA_COLLECTION,
    Chunk,
    Document,
    ExtractionStatus,
    build_storage_path,
    compute_sha256,
    make_chunk_id,
    make_document_id,
)
from backend.app.search.models import SearchHit, SearchMethod

CONTENT = "Texto sintético de prueba para DocuSearch.".encode("utf-8")


def _document(**overrides) -> Document:
    sha = compute_sha256(CONTENT)
    doc_id = make_document_id(sha)
    params = dict(
        content=CONTENT,
        original_filename="apuntes.txt",
        mime_type="text/plain",
        storage_path=build_storage_path(doc_id, ".txt", "user"),
    )
    params.update(overrides)
    return Document.new(**params)


def test_document_id_is_stable_and_depends_on_content_and_collection() -> None:
    sha = compute_sha256(CONTENT)
    assert make_document_id(sha) == make_document_id(sha)
    assert make_document_id(sha) != make_document_id(compute_sha256(b"otro"))
    assert make_document_id(sha) != make_document_id(sha, WIKIPEDIA_COLLECTION)
    assert make_document_id(sha).startswith("doc_") and len(make_document_id(sha)) == 28


def test_document_new_fills_hash_size_title_and_defaults() -> None:
    document = _document()
    assert document.sha256 == compute_sha256(CONTENT)
    assert document.size_bytes == len(CONTENT)
    assert document.title == "apuntes"
    assert document.extraction_status is ExtractionStatus.PENDING
    assert document.created_at.tzinfo is not None
    assert document.storage_path == f"user/{document.doc_id}.txt"


@pytest.mark.parametrize(
    "bad_path", ["../secreto.txt", "/etc/passwd", "C:/x.txt", "a\\b.txt", "a/../b.txt", ""]
)
def test_document_rejects_unsafe_storage_paths(bad_path: str) -> None:
    with pytest.raises(ValidationError):
        _document(storage_path=bad_path)


def test_document_rejects_filename_with_separators() -> None:
    with pytest.raises(ValidationError):
        _document(original_filename="../../evil.txt")


def test_document_rejects_mismatched_doc_id() -> None:
    data = _document().model_dump()
    data["doc_id"] = make_document_id(compute_sha256(b"otro contenido"))
    with pytest.raises(ValidationError, match="doc_id"):
        Document.model_validate(data)


def test_failed_extraction_requires_error_message() -> None:
    document = _document()
    with pytest.raises(ValidationError):
        Document.model_validate(
            {**document.model_dump(), "extraction_status": ExtractionStatus.FAILED}
        )


def test_document_json_roundtrip() -> None:
    document = _document(source_uri="https://es.wikipedia.org/wiki/Prueba")
    restored = Document.model_validate_json(document.model_dump_json())
    assert restored == document


def test_chunk_new_builds_stable_id_and_counts_words() -> None:
    doc_id = _document().doc_id
    chunk = Chunk.new(doc_id=doc_id, ordinal=3, text="uno dos tres", char_start=10, char_end=22, page_start=2)
    assert chunk.chunk_id == make_chunk_id(doc_id, 3) == f"{doc_id}_c00003"
    assert chunk.word_count == 3
    assert (chunk.page_start, chunk.page_end) == (2, 2)


def test_chunk_without_page_is_allowed_for_docx_and_txt() -> None:
    chunk = Chunk.new(doc_id=_document().doc_id, ordinal=0, text="hola", char_start=0, char_end=4)
    assert chunk.page_start is None and chunk.page_end is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"char_start": 5, "char_end": 5},
        {"char_start": 0, "char_end": 4, "page_start": 0},
        {"char_start": 0, "char_end": 4, "page_start": 3, "page_end": 2},
        {"char_start": -1, "char_end": 4},
    ],
)
def test_chunk_rejects_invalid_offsets_and_pages(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        Chunk.new(doc_id=_document().doc_id, ordinal=0, text="hola", **kwargs)


def test_chunk_rejects_empty_text_and_mismatched_id() -> None:
    doc_id = _document().doc_id
    with pytest.raises(ValidationError):
        Chunk.new(doc_id=doc_id, ordinal=0, text="", char_start=0, char_end=1)
    with pytest.raises(ValidationError):
        Chunk(
            chunk_id=make_chunk_id(doc_id, 1),
            doc_id=doc_id,
            ordinal=0,
            text="hola",
            char_start=0,
            char_end=4,
            word_count=1,
        )


def test_search_hit_contract_references_document_chunk_and_page() -> None:
    document = _document()
    chunk = Chunk.new(doc_id=document.doc_id, ordinal=0, text="hola", char_start=0, char_end=4, page_start=1)
    hit = SearchHit(
        rank=1,
        score=0.87,
        method=SearchMethod.BM25,
        doc_id=document.doc_id,
        chunk_id=chunk.chunk_id,
        title=document.title,
        original_filename=document.original_filename,
        snippet=chunk.text,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
    )
    assert hit.model_dump(mode="json")["method"] == "bm25"
