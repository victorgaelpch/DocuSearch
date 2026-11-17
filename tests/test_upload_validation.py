"""Pruebas unitarias de validación de carga (DOC-04)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.documents.readers import DOCX_MIME, PDF_MIME, TXT_MIME
from backend.app.documents.validation import (
    UploadValidationError,
    sanitize_filename,
    validate_upload,
)

FIXTURES = Path(__file__).parent / "fixtures"
MB = 1024 * 1024


def _validate(name: str, data: bytes, max_bytes: int = 5 * MB, max_docx: int = 50 * MB):
    return validate_upload(name, data, max_bytes=max_bytes, max_docx_uncompressed_bytes=max_docx)


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("informe.pdf", "informe.pdf"),
        ("../../etc/passwd.txt", "passwd.txt"),
        ("C:\\Users\\x\\notas.txt", "notas.txt"),
        ("ma\u0301s\u202e.txt", "más.txt"),  # NFC y sin caracteres de control/formato
        ("  .oculto.docx  ", "oculto.docx"),
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "..", "/", "CON.txt", "nul.pdf", "\x00\x01"])
def test_sanitize_filename_rejects_invalid_names(raw) -> None:
    with pytest.raises(UploadValidationError) as info:
        sanitize_filename(raw)
    assert info.value.code == "invalid_filename"


def test_sanitize_filename_truncates_long_names_keeping_extension() -> None:
    name = sanitize_filename("a" * 400 + ".pdf")
    assert len(name) == 255 and name.endswith(".pdf")


@pytest.mark.parametrize(
    ("name", "mime"),
    [("muestra.pdf", PDF_MIME), ("muestra.docx", DOCX_MIME), ("muestra.txt", TXT_MIME)],
)
def test_valid_fixtures_pass_and_detect_real_mime(name: str, mime: str) -> None:
    result = _validate(name.upper(), (FIXTURES / name).read_bytes())
    assert result.mime_type == mime


@pytest.mark.parametrize(
    ("name", "data", "code", "status"),
    [
        ("virus.exe", b"MZ\x90", "unsupported_format", 415),
        ("viejo.doc", b"\xd0\xcf\x11\xe0", "unsupported_format", 415),
        ("vacio.pdf", b"", "empty_file", 400),
        ("falso.pdf", b"hola, no soy un PDF", "content_mismatch", 415),
        ("falso.docx", b"%PDF-1.7 ...", "content_mismatch", 415),
        ("roto.docx", b"PK\x03\x04" + b"\x00" * 30, "corrupt_file", 422),
        ("zip.docx", _zip({"a.txt": b"hola"}), "content_mismatch", 415),
        (
            "macros.docx",
            _zip({"[Content_Types].xml": b"<x/>", "word/document.xml": b"<x/>", "word/vbaProject.bin": b"\x00"}),
            "macros_not_allowed",
            415,
        ),
        ("programa.txt", b"MZ\x90\x00\x03", "content_mismatch", 415),
        ("pdf.txt", b"%PDF-1.4 hola", "content_mismatch", 415),
        ("binario.txt", b"abc\x00def", "content_mismatch", 415),
    ],
)
def test_invalid_uploads_are_rejected(name: str, data: bytes, code: str, status: int) -> None:
    with pytest.raises(UploadValidationError) as info:
        _validate(name, data)
    assert (info.value.code, info.value.status_code) == (code, status)


def test_size_limit_is_enforced() -> None:
    with pytest.raises(UploadValidationError) as info:
        _validate("grande.txt", b"a" * (MB + 1), max_bytes=MB)
    assert info.value.status_code == 413


def test_docx_zip_bomb_is_rejected_by_uncompressed_size() -> None:
    bomb = _zip(
        {"[Content_Types].xml": b"<x/>", "word/document.xml": b"<x/>", "relleno.bin": b"\x00" * (2 * MB)}
    )
    assert len(bomb) < 100 * 1024  # comprime muchísimo
    with pytest.raises(UploadValidationError) as info:
        _validate("bomba.docx", bomb, max_docx=MB)
    assert info.value.code == "docx_too_large"


def test_utf16_txt_with_bom_is_accepted() -> None:
    assert _validate("u16.txt", "hola".encode("utf-16")).mime_type == TXT_MIME


def test_settings_from_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCUSEARCH_MAX_UPLOAD_MB", "2")
    settings = Settings.from_env(tmp_path)
    assert settings.max_upload_bytes == 2 * MB
    assert settings.paths.root == tmp_path.resolve()
    monkeypatch.setenv("DOCUSEARCH_MAX_UPLOAD_MB", "-1")
    with pytest.raises(ValueError):
        Settings.from_env(tmp_path)
    monkeypatch.setenv("DOCUSEARCH_MAX_UPLOAD_MB", "abc")
    with pytest.raises(ValueError):
        Settings.from_env(tmp_path)
