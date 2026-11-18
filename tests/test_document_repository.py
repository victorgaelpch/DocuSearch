"""Pruebas de integración del repositorio SQLite y del almacén de originales (DOC-02)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.app.config import get_data_paths
from backend.app.documents import (
    WIKIPEDIA_COLLECTION,
    Chunk,
    Document,
    DocumentNotFoundError,
    DocumentRepository,
    DuplicateDocumentError,
    ExtractionStatus,
    OriginalStore,
    SchemaVersionError,
    SourceType,
    UnsafePathError,
    build_storage_path,
    compute_sha256,
    make_document_id,
)


def _make(content: bytes, name: str = "nota.txt", collection: str = "user") -> Document:
    doc_id = make_document_id(compute_sha256(content), collection)
    return Document.new(
        content=content,
        original_filename=name,
        mime_type="text/plain",
        storage_path=build_storage_path(doc_id, Path(name).suffix, collection),
        collection=collection,
        source_type=SourceType.UPLOAD if collection == "user" else SourceType.CORPUS,
    )


def _chunks(doc_id: str, texts: list[str], page: int | None = None) -> list[Chunk]:
    result, offset = [], 0
    for ordinal, text in enumerate(texts):
        result.append(
            Chunk.new(
                doc_id=doc_id,
                ordinal=ordinal,
                text=text,
                char_start=offset,
                char_end=offset + len(text),
                page_start=page,
            )
        )
        offset += len(text) + 1
    return result


@pytest.fixture()
def paths(tmp_path: Path):
    return get_data_paths(tmp_path / "data").ensure()


@pytest.fixture()
def repo(paths) -> DocumentRepository:
    return DocumentRepository(paths.metadata_db)


@pytest.fixture()
def store(paths) -> OriginalStore:
    return OriginalStore(paths.originals_dir)


def test_data_paths_separate_originals_metadata_and_indexes(paths, monkeypatch, tmp_path) -> None:
    assert paths.originals_dir.is_dir() and paths.indexes_dir.is_dir()
    assert paths.metadata_db.parent == paths.root
    assert len({paths.originals_dir, paths.indexes_dir, paths.metadata_db}) == 3
    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(tmp_path / "otra"))
    assert get_data_paths().root == (tmp_path / "otra").resolve()


def test_document_keeps_reference_to_original_file(repo, store) -> None:
    content = b"contenido original"
    document = repo.add_document(_make(content))
    store.save(document.storage_path, content)

    loaded = repo.get_document(document.doc_id)
    assert loaded == document
    assert store.read(loaded.storage_path) == content
    assert store.resolve(loaded.storage_path).parent.parent == store.root


def test_metadata_persists_across_repository_instances(paths) -> None:
    document = DocumentRepository(paths.metadata_db).add_document(_make(b"persistente"))
    reopened = DocumentRepository(paths.metadata_db)
    assert reopened.get_document(document.doc_id) == document
    assert reopened.count_documents() == 1


def test_duplicate_content_in_same_collection_is_rejected(repo) -> None:
    first = repo.add_document(_make(b"igual", "a.txt"))
    with pytest.raises(DuplicateDocumentError) as info:
        repo.add_document(_make(b"igual", "b.txt"))
    assert info.value.existing.doc_id == first.doc_id


def test_same_content_in_wikipedia_collection_is_kept_separate(repo) -> None:
    user_doc = repo.add_document(_make(b"igual"))
    wiki_doc = repo.add_document(_make(b"igual", collection=WIKIPEDIA_COLLECTION))
    assert user_doc.doc_id != wiki_doc.doc_id
    assert [d.doc_id for d in repo.list_documents("user")] == [user_doc.doc_id]
    assert [d.doc_id for d in repo.list_documents(WIKIPEDIA_COLLECTION)] == [wiki_doc.doc_id]


def test_missing_document_raises_controlled_error(repo) -> None:
    missing = make_document_id(compute_sha256(b"no existe"))
    assert repo.get_document_or_none(missing) is None
    with pytest.raises(DocumentNotFoundError):
        repo.get_document(missing)
    with pytest.raises(DocumentNotFoundError):
        repo.delete_document(missing)


def test_chunks_include_parent_document_and_page(repo) -> None:
    document = repo.add_document(_make(b"pdf simulado", "informe.pdf"))
    repo.replace_chunks(document.doc_id, _chunks(document.doc_id, ["primer fragmento", "segundo"], page=4))
    stored = repo.get_chunks(document.doc_id)
    assert [c.ordinal for c in stored] == [0, 1]
    assert all(c.doc_id == document.doc_id and c.page_start == 4 for c in stored)
    assert repo.get_chunk(stored[1].chunk_id) == stored[1]


def test_reindexing_replaces_chunks_with_same_schema_and_ids(repo) -> None:
    document = repo.add_document(_make(b"reindexar"))
    repo.replace_chunks(document.doc_id, _chunks(document.doc_id, ["a b", "c d", "e f"]))
    before_ids = [c.chunk_id for c in repo.get_chunks(document.doc_id)]

    repo.replace_chunks(document.doc_id, _chunks(document.doc_id, ["a b c", "d e f"]))
    after = repo.get_chunks(document.doc_id)
    assert [c.chunk_id for c in after] == before_ids[:2]
    assert [c.text for c in after] == ["a b c", "d e f"]
    assert list(repo.iter_chunks()) == after


def test_failed_reindex_rolls_back_and_keeps_previous_chunks(repo) -> None:
    document = repo.add_document(_make(b"rollback"))
    original = _chunks(document.doc_id, ["uno", "dos"])
    repo.replace_chunks(document.doc_id, original)

    duplicated = _chunks(document.doc_id, ["x"]) * 2
    with pytest.raises(ValueError):
        repo.replace_chunks(document.doc_id, duplicated)
    other = repo.add_document(_make(b"otro documento"))
    with pytest.raises(ValueError):
        repo.replace_chunks(document.doc_id, _chunks(other.doc_id, ["ajeno"]))
    assert repo.get_chunks(document.doc_id) == original


def test_replace_chunks_for_missing_document_fails(repo) -> None:
    missing = make_document_id(compute_sha256(b"fantasma"))
    with pytest.raises(DocumentNotFoundError):
        repo.replace_chunks(missing, _chunks(missing, ["x"]))


def test_update_extraction_status(repo) -> None:
    document = repo.add_document(_make(b"estado", "escaneo.pdf"))
    updated = repo.update_extraction(document.doc_id, ExtractionStatus.NEEDS_OCR, page_count=3)
    assert updated.extraction_status is ExtractionStatus.NEEDS_OCR
    assert repo.get_document(document.doc_id).page_count == 3

    with pytest.raises(Exception):
        repo.update_extraction(document.doc_id, ExtractionStatus.FAILED)
    assert repo.get_document(document.doc_id).extraction_status is ExtractionStatus.NEEDS_OCR

    failed = repo.update_extraction(document.doc_id, ExtractionStatus.FAILED, error="PDF dañado")
    assert repo.get_document(document.doc_id).extraction_error == failed.extraction_error


def test_delete_document_cascades_to_chunks(repo) -> None:
    document = repo.add_document(_make(b"borrar"))
    repo.replace_chunks(document.doc_id, _chunks(document.doc_id, ["x y"]))
    repo.delete_document(document.doc_id)
    assert repo.get_chunks(document.doc_id) == []
    assert repo.count_documents() == 0


def test_list_documents_pagination(repo) -> None:
    for i in range(5):
        repo.add_document(_make(f"doc {i}".encode()))
    assert len(repo.list_documents(limit=2)) == 2
    assert len(repo.list_documents(limit=10, offset=4)) == 1
    with pytest.raises(ValueError):
        repo.list_documents(limit=0)


def test_unknown_schema_version_is_rejected(tmp_path: Path) -> None:
    db = tmp_path / "futuro.db"
    connection = sqlite3.connect(db)
    connection.execute("PRAGMA user_version = 99")
    connection.close()
    with pytest.raises(SchemaVersionError):
        DocumentRepository(db)


@pytest.mark.parametrize("bad", ["../fuera.txt", "/abs.txt", "a/../../b", "C:/x", "a\\b", ""])
def test_original_store_blocks_path_traversal(store, bad: str) -> None:
    with pytest.raises(UnsafePathError):
        store.resolve(bad)


def test_original_store_does_not_overwrite_different_content(store) -> None:
    doc_id = make_document_id(compute_sha256(b"a"))
    path = build_storage_path(doc_id, ".TXT", "user")
    assert path.endswith(".txt")
    store.save(path, b"a")
    store.save(path, b"a")  # idempotente
    with pytest.raises(FileExistsError):
        store.save(path, b"b")
    assert store.delete(path) and not store.exists(path)


@pytest.mark.parametrize(
    "args", [("doc_x", ".txt", "user"), (None, ".t/xt", "user"), (None, ".txt", "../user")]
)
def test_build_storage_path_validates_inputs(args) -> None:
    doc_id = args[0] or make_document_id(compute_sha256(b"z"))
    with pytest.raises(UnsafePathError):
        build_storage_path(doc_id, args[1], args[2])


def test_get_chunks_by_ids_batches_and_skips_missing(repo: DocumentRepository) -> None:
    document = _make(b"contenido para lotes")
    repo.add_document(document)
    chunks = _chunks(document.doc_id, [f"texto {i}" for i in range(600)])
    repo.replace_chunks(document.doc_id, chunks)
    wanted = [c.chunk_id for c in reversed(chunks)] + ["doc_inexistente_c00000", chunks[0].chunk_id]
    found = repo.get_chunks_by_ids(wanted)
    assert len(found) == 600 and found[chunks[599].chunk_id].text == "texto 599"
    assert repo.get_chunks_by_ids([]) == {}
