"""Pruebas de fragmentación 200/30 y procedencia (DOC-07)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.app.cli import main as cli_main
from backend.app.config import Settings
from backend.app.documents import compute_sha256, extract_document, make_document_id
from backend.app.documents.service import DocumentService
from backend.app.main import create_app
from backend.app.nlp.chunking import ChunkingConfig, chunk_extraction, chunk_text
from tests.auth_helpers import admin_client

DOC_ID = make_document_id(compute_sha256(b"chunking"))
FIXTURES = Path(__file__).parent / "fixtures"


def _words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_default_configuration_is_200_30() -> None:
    config = ChunkingConfig()
    assert (config.chunk_size, config.overlap, config.step) == (200, 30, 170)
    settings = Settings.from_env(".")
    assert (settings.chunk_size, settings.chunk_overlap) == (200, 30)


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (10, 10), (10, 11), (10, -1)])
def test_invalid_configuration(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        ChunkingConfig(size, overlap)


def test_windows_and_overlap_of_30_words() -> None:
    text = _words(500)
    chunks = chunk_text(text, DOC_ID)
    words = [c.text.split() for c in chunks]
    assert [len(w) for w in words] == [200, 200, 160]
    assert words[0][-30:] == words[1][:30]
    assert words[1][-30:] == words[2][:30]
    assert words[0][0] == "w0" and words[1][0] == "w170" and words[2][0] == "w340"
    assert words[-1][-1] == "w499"


def test_reconstruction_from_offsets_covers_whole_text() -> None:
    text = "  Inicio   del\ttexto.\n\n" + _words(450) + "  fin. "
    chunks = chunk_text(text, DOC_ID, ChunkingConfig(100, 20))
    for chunk in chunks:
        assert text[chunk.char_start : chunk.char_end] == chunk.text
        assert chunk.text == chunk.text.strip() and chunk.text
    assert chunks[0].char_start == text.index("Inicio")
    assert chunks[-1].char_end == text.rindex("fin.") + len("fin.")
    # sin huecos: cada fragmento empieza antes de que termine el anterior
    for previous, current in zip(chunks, chunks[1:]):
        assert current.char_start < previous.char_end


def test_short_text_produces_single_chunk_and_empty_none() -> None:
    chunks = chunk_text("Solo unas pocas palabras.", DOC_ID)
    assert len(chunks) == 1 and chunks[0].word_count == 4
    assert chunk_text("", DOC_ID) == []
    assert chunk_text("   \n\t ", DOC_ID) == []


def test_exact_multiple_does_not_create_redundant_tail() -> None:
    chunks = chunk_text(_words(200), DOC_ID)
    assert len(chunks) == 1
    chunks = chunk_text(_words(370), DOC_ID)  # 0-199, 170-369
    assert [c.word_count for c in chunks] == [200, 200]


def test_ids_are_stable_and_linked_to_document() -> None:
    first = chunk_text(_words(600), DOC_ID)
    second = chunk_text(_words(600), DOC_ID)
    assert first == second  # determinista
    assert [c.chunk_id for c in first] == [f"{DOC_ID}_c{i:05d}" for i in range(len(first))]
    assert all(c.doc_id == DOC_ID for c in first)


def test_zero_overlap() -> None:
    chunks = chunk_text(_words(25), DOC_ID, ChunkingConfig(10, 0))
    assert [c.word_count for c in chunks] == [10, 10, 5]


def _multi_page_pdf(words_per_page: int, pages: int) -> bytes:
    document = pymupdf.open()
    for page_number in range(pages):
        page = document.new_page()
        words = [f"p{page_number + 1}w{i}" for i in range(words_per_page)]
        lines = [" ".join(words[i : i + 8]) for i in range(0, len(words), 8)]
        page.insert_text((40, 40), "\n".join(lines), fontsize=8)
    data = document.tobytes()
    document.close()
    return data


def test_pdf_chunks_keep_page_provenance() -> None:
    extraction = extract_document(_multi_page_pdf(150, 3), "paginas.pdf")
    chunks = chunk_extraction(extraction, DOC_ID)
    assert [(c.page_start, c.page_end) for c in chunks] == [(1, 2), (2, 3), (3, 3)]
    for chunk in chunks:
        first_word, last_word = chunk.text.split()[0], chunk.text.split()[-1]
        assert first_word.startswith(f"p{chunk.page_start}w")
        assert last_word.startswith(f"p{chunk.page_end}w")


def test_docx_and_txt_chunks_have_no_page() -> None:
    for name in ("muestra.docx", "muestra.txt"):
        extraction = extract_document((FIXTURES / name).read_bytes(), name)
        chunks = chunk_extraction(extraction, DOC_ID)
        assert len(chunks) == 1
        assert chunks[0].page_start is None and chunks[0].page_end is None


# -- integración con la carga ------------------------------------------------------


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(tmp_path / "data")


def test_upload_persists_chunks_and_exposes_them(settings: Settings) -> None:
    client = admin_client(settings)
    data = _multi_page_pdf(150, 3)
    body = client.post("/documents", files={"file": ("tres.pdf", data)}).json()
    assert body["chunk_count"] == 3
    assert body["metadata"]["chunking"] == {"version": 1, "chunk_size": 200, "overlap": 30}

    listing = client.get(f"/documents/{body['doc_id']}/chunks").json()
    assert listing["chunking"]["chunk_size"] == 200
    assert [c["ordinal"] for c in listing["items"]] == [0, 1, 2]
    assert listing["items"][0]["page_start"] == 1 and listing["items"][-1]["page_end"] == 3
    assert client.get(f"/documents/doc_{'0' * 24}/chunks").status_code == 404


def test_rechunk_with_new_configuration(settings: Settings) -> None:
    service = DocumentService(settings)
    result = service.ingest("largo.txt", _words(1000).encode())
    assert len(result.chunks) == 6  # pasos de 170 palabras

    smaller = DocumentService(replace(settings, chunk_size=100, chunk_overlap=0))
    report = smaller.rechunk()
    assert report.documents == 1 and report.chunks == 10 and report.failed == {}
    stored = smaller.get_chunks(result.document.doc_id)
    assert [c.word_count for c in stored] == [100] * 10
    assert smaller.get_document(result.document.doc_id).extra["chunking"]["chunk_size"] == 100


def test_rechunk_reports_missing_original_and_keeps_chunks(settings: Settings) -> None:
    service = DocumentService(settings)
    result = service.ingest("nota.txt", _words(300).encode())
    service.store.delete(result.document.storage_path)
    report = service.rechunk()
    assert result.document.doc_id in report.failed
    assert len(service.get_chunks(result.document.doc_id)) == len(result.chunks)


def test_failed_chunk_persistence_rolls_back_document_and_original(settings: Settings, monkeypatch) -> None:
    service = DocumentService(settings)

    def boom(*args, **kwargs):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(service.repository, "replace_chunks", boom)
    with pytest.raises(RuntimeError):
        service.ingest("nota.txt", b"texto de prueba suficiente")
    assert service.repository.count_documents() == 0
    assert not any(settings.paths.originals_dir.rglob("*.txt"))


def test_cli_rechunk(settings: Settings, monkeypatch, capsys) -> None:
    DocumentService(settings).ingest("nota.txt", _words(250).encode())
    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(settings.paths.root))
    assert cli_main(["rechunk"]) == 0
    assert '"documents": 1' in capsys.readouterr().out
