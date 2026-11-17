"""Pruebas de los lectores PDF, DOCX y TXT (DOC-03).

Usa los fixtures sintéticos de ``tests/fixtures`` (ver ``generate_fixtures.py``)
y archivos dañados generados en memoria.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import docx
import pymupdf
import pytest

from backend.app.documents import (
    SUPPORTED_EXTENSIONS,
    Document,
    DocumentRepository,
    ExtractionStatus,
    OriginalStore,
    UnsupportedFormatError,
    build_document,
    extract_document,
    get_reader,
)
from backend.app.documents.readers import DOCX_MIME, PDF_MIME, SECTION_SEPARATOR, TXT_MIME

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _assert_offsets_consistent(result) -> None:
    for section in result.sections:
        assert result.text[section.char_start : section.char_end] == section.text


def _pdf_bytes(pages: list[str], password: str | None = None) -> bytes:
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    options = {}
    if password:
        options = dict(
            encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password
        )
    data = document.tobytes(**options)
    document.close()
    return data


# -- formatos válidos ---------------------------------------------------------


def test_pdf_extracts_text_per_page_with_metadata() -> None:
    spec = EXPECTED["muestra.pdf"]
    result = extract_document(_fixture("muestra.pdf"), "muestra.pdf")

    assert result.status is ExtractionStatus.EXTRACTED
    assert result.mime_type == PDF_MIME
    assert result.page_count == 2
    assert result.title == spec["title"]
    assert result.metadata["author"] == "DocuSearch tests"
    assert [s.text for s in result.sections] == spec["pages"]
    assert [s.page_number for s in result.sections] == [1, 2]
    assert result.text == SECTION_SEPARATOR.join(spec["pages"])
    _assert_offsets_consistent(result)
    second_page_offset = result.text.index("Segunda página")
    assert result.page_for_offset(second_page_offset) == 2
    assert result.page_for_offset(0) == 1


def test_docx_preserves_paragraphs_and_tables_in_document_order() -> None:
    spec = EXPECTED["muestra.docx"]
    result = extract_document(_fixture("muestra.docx"), "muestra.docx")

    assert result.status is ExtractionStatus.EXTRACTED
    assert result.mime_type == DOCX_MIME
    assert result.text == spec["text"]
    assert result.title == spec["title"]
    assert result.page_count is None
    assert all(s.page_number is None for s in result.sections)
    assert result.metadata["paragraphs"] == 3 and result.metadata["table_rows"] == 2
    _assert_offsets_consistent(result)


def test_txt_utf8_is_read_exactly() -> None:
    result = extract_document(_fixture("muestra.txt"), "muestra.txt")
    assert result.status is ExtractionStatus.EXTRACTED
    assert result.mime_type == TXT_MIME
    assert result.text == EXPECTED["muestra.txt"]["text"]
    assert result.metadata["encoding"] == "utf-8"
    assert result.title == "muestra"
    assert result.warnings == []


def test_result_includes_size_and_hash_usable_by_index() -> None:
    data = _fixture("muestra.txt")
    result = extract_document(data, "muestra.txt")
    assert result.size_bytes == len(data)
    assert len(result.sha256) == 64
    assert result.word_count == len(EXPECTED["muestra.txt"]["text"].split())


@pytest.mark.parametrize(
    ("data", "encoding", "has_warning"),
    [
        ("Acción y\r\nmás texto".encode("utf-8-sig"), "utf-8-sig", False),
        ("Acción y\r\nmás texto".encode("utf-16"), "utf-16", False),
        ("Acción y\r\nmás texto".encode("cp1252"), "cp1252", True),
    ],
)
def test_txt_controlled_decoding(data: bytes, encoding: str, has_warning: bool) -> None:
    result = extract_document(data, "nota.txt")
    assert result.status is ExtractionStatus.EXTRACTED
    assert result.text == "Acción y\nmás texto"
    assert result.metadata["encoding"] == encoding
    assert bool(result.warnings) is has_warning


def test_extension_is_case_insensitive_and_path_is_stripped() -> None:
    result = extract_document(_fixture("muestra.pdf"), "carpeta/INFORME.PDF")
    assert result.status is ExtractionStatus.EXTRACTED
    assert result.filename == "INFORME.PDF" and result.extension == ".pdf"


# -- vacíos, dañados y no admitidos ------------------------------------------


@pytest.mark.parametrize("name", ["vacio.pdf", "vacio.docx", "vacio.txt"])
def test_empty_files_produce_controlled_empty_status(name: str) -> None:
    result = extract_document(b"", name)
    assert result.status is ExtractionStatus.EMPTY
    assert "vacío" in result.error
    assert result.text == "" and result.sections == []


def test_whitespace_only_txt_is_empty() -> None:
    result = extract_document(b"  \r\n\t ", "blanco.txt")
    assert result.status is ExtractionStatus.EMPTY
    assert result.error


def _zip_without_docx_parts() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hola.txt", "no es un docx")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("data", "name"),
    [
        (b"esto no es un PDF", "falso.pdf"),
        (b"%PDF-1.7\n" + b"\x00\xff basura " * 20, "truncado.pdf"),
        (b"no es un zip", "falso.docx"),
        (b"PK\x03\x04" + b"\x00" * 40, "zip_roto.docx"),
        (_zip_without_docx_parts(), "zip_sin_word.docx"),
        (_fixture("muestra.pdf"), "pdf_renombrado.docx"),
        (_fixture("muestra.docx"), "docx_renombrado.pdf"),
        (b"\x00\x01\x02binario\x00", "binario.txt"),
    ],
)
def test_corrupt_or_mismatched_files_fail_with_error(data: bytes, name: str) -> None:
    result = extract_document(data, name)
    assert result.status is ExtractionStatus.FAILED
    assert result.error
    assert result.text == ""


def test_password_protected_pdf_fails_with_clear_error() -> None:
    result = extract_document(_pdf_bytes(["secreto"], password="clave"), "cifrado.pdf")
    assert result.status is ExtractionStatus.FAILED
    assert "contraseña" in result.error


@pytest.mark.parametrize("name", ["programa.exe", "antiguo.doc", "sin_extension", "hoja.xlsx"])
def test_unsupported_formats_raise_without_reading(name: str) -> None:
    with pytest.raises(UnsupportedFormatError, match="no admitido"):
        extract_document(b"MZ\x90\x00", name)
    with pytest.raises(UnsupportedFormatError):
        get_reader(name)
    assert SUPPORTED_EXTENSIONS == (".pdf", ".docx", ".txt")


# -- PDF escaneados / sin texto ----------------------------------------------


def test_pdf_without_text_layer_requires_ocr() -> None:
    result = extract_document(_pdf_bytes(["", ""]), "escaneado.pdf")
    assert result.status is ExtractionStatus.NEEDS_OCR
    assert result.page_count == 2
    assert result.metadata["pages_without_text"] == [1, 2]


def test_pdf_with_some_empty_pages_warns_and_keeps_page_numbers() -> None:
    result = extract_document(_pdf_bytes(["Primera", "", "Tercera"]), "mixto.pdf")
    assert result.status is ExtractionStatus.EXTRACTED
    assert any("OCR" in w for w in result.warnings)
    assert [(s.page_number, s.text) for s in result.sections] == [
        (1, "Primera"),
        (2, ""),
        (3, "Tercera"),
    ]
    assert result.page_for_offset(result.text.index("Tercera")) == 3
    _assert_offsets_consistent(result)


def test_docx_without_text_is_empty() -> None:
    buffer = io.BytesIO()
    docx.Document().save(buffer)
    result = extract_document(buffer.getvalue(), "vacio_word.docx")
    assert result.status is ExtractionStatus.EMPTY


# -- integración con el modelo de DOC-02 --------------------------------------


@pytest.mark.parametrize("name", ["muestra.pdf", "muestra.docx", "muestra.txt"])
def test_build_document_persists_metadata_and_original(tmp_path: Path, name: str) -> None:
    data = _fixture(name)
    result = extract_document(data, name)
    document = build_document(result)

    repo = DocumentRepository(tmp_path / "metadata.db")
    store = OriginalStore(tmp_path / "originals")
    repo.add_document(document)
    store.save(document.storage_path, data)

    loaded = repo.get_document(document.doc_id)
    assert isinstance(loaded, Document)
    assert loaded.extraction_status is ExtractionStatus.EXTRACTED
    assert loaded.mime_type == result.mime_type
    assert loaded.page_count == result.page_count
    assert loaded.storage_path.endswith(Path(name).suffix)
    assert store.read(loaded.storage_path) == data


def test_build_document_records_failed_extraction() -> None:
    document = build_document(extract_document(b"roto", "roto.pdf"))
    assert document.extraction_status is ExtractionStatus.FAILED
    assert document.extraction_error
