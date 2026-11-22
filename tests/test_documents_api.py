"""Pruebas de integración de los endpoints /documents (DOC-04)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from tests.auth_helpers import admin_client

FIXTURES = Path(__file__).parent / "fixtures"
MIMES = {
    "muestra.pdf": "application/pdf",
    "muestra.docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "muestra.txt": "text/plain",
}


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(tmp_path / "data")


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    return admin_client(settings)


def _upload(client: TestClient, name: str, data: bytes, content_type: str = "application/octet-stream"):
    return client.post("/documents", files={"file": (name, data, content_type)})


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _originals(settings: Settings) -> list[Path]:
    root = settings.paths.originals_dir
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


@pytest.mark.parametrize("name", ["muestra.pdf", "muestra.docx", "muestra.txt"])
def test_upload_pdf_docx_txt_and_query_by_id(client: TestClient, settings: Settings, name: str) -> None:
    data = _fixture(name)
    response = _upload(client, name, data)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["doc_id"].startswith("doc_")
    assert body["original_filename"] == name
    assert body["mime_type"] == MIMES[name]
    assert body["size_bytes"] == len(data)
    assert body["extraction_status"] == "extracted"
    assert body["word_count"] > 0
    assert "storage_path" not in body

    detail = client.get(f"/documents/{body['doc_id']}")
    assert detail.status_code == 200
    assert detail.json()["sha256"] == body["sha256"]
    assert detail.json()["page_count"] == (2 if name.endswith(".pdf") else None)

    stored = _originals(settings)
    assert len(stored) == 1 and stored[0].read_bytes() == data
    assert name not in stored[0].name  # el original no usa el nombre del cliente


def test_download_returns_original_as_attachment(client: TestClient) -> None:
    data = _fixture("muestra.pdf")
    doc_id = _upload(client, "Informe final.pdf", data).json()["doc_id"]
    response = client.get(f"/documents/{doc_id}/download")
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_download_handles_non_ascii_filenames(client: TestClient) -> None:
    doc_id = _upload(client, "Apuntes de ñandú.txt", _fixture("muestra.txt")).json()["doc_id"]
    response = client.get(f"/documents/{doc_id}/download")
    assert response.status_code == 200
    assert "filename*=utf-8''" in response.headers["content-disposition"]


def test_list_documents_with_pagination(client: TestClient) -> None:
    for name in MIMES:
        assert _upload(client, name, _fixture(name)).status_code == 201
    response = client.get("/documents", params={"limit": 2})
    body = response.json()
    assert response.status_code == 200
    assert body["total"] == 3 and len(body["items"]) == 2
    assert client.get("/documents", params={"offset": 2}).json()["items"][0]["doc_id"]
    assert client.get("/documents", params={"limit": 0}).status_code == 422


def test_empty_list(client: TestClient) -> None:
    assert client.get("/documents").json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_duplicate_upload_returns_409_with_existing_id(client: TestClient, settings: Settings) -> None:
    first = _upload(client, "a.txt", _fixture("muestra.txt")).json()
    response = _upload(client, "b.txt", _fixture("muestra.txt"))
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "duplicate_document",
        "message": "el documento ya fue cargado",
        "doc_id": first["doc_id"],
    }
    assert len(_originals(settings)) == 1


@pytest.mark.parametrize(
    ("name", "data", "status", "code"),
    [
        ("vacio.txt", b"", 400, "empty_file"),
        ("blanco.txt", b"   \n\t ", 422, "no_text"),
        ("virus.exe", b"MZ\x90\x00", 415, "unsupported_format"),
        ("script.sh", b"#!/bin/sh\nrm -rf /", 415, "unsupported_format"),
        ("falso.pdf", b"<html>no es pdf</html>", 415, "content_mismatch"),
        ("truncado.pdf", b"%PDF-1.7\n" + b"\x00\xffbasura" * 30, 422, "corrupt_file"),
        ("falso.docx", b"texto plano", 415, "content_mismatch"),
        ("ejecutable.txt", b"MZ\x90\x00\x03\x00", 415, "content_mismatch"),
    ],
)
def test_invalid_files_are_rejected_and_not_stored(
    client: TestClient, settings: Settings, name: str, data: bytes, status: int, code: str
) -> None:
    response = _upload(client, name, data)
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"]
    assert _originals(settings) == []
    assert client.get("/documents").json()["total"] == 0


def test_client_content_type_is_not_trusted(client: TestClient) -> None:
    response = _upload(client, "falso.pdf", b"no soy pdf", content_type="application/pdf")
    assert response.status_code == 415
    ok = _upload(client, "muestra.pdf", _fixture("muestra.pdf"), content_type="text/plain")
    assert ok.status_code == 201 and ok.json()["mime_type"] == "application/pdf"


def test_path_traversal_filename_is_sanitized(client: TestClient, settings: Settings) -> None:
    response = _upload(client, "../../../evil.txt", _fixture("muestra.txt"))
    assert response.status_code == 201
    assert response.json()["original_filename"] == "evil.txt"
    stored = _originals(settings)
    assert len(stored) == 1
    assert settings.paths.originals_dir in stored[0].parents


def test_upload_size_limit_returns_413(settings: Settings) -> None:
    small = admin_client(replace(settings, max_upload_bytes=1024))
    response = _upload(small, "grande.txt", b"a" * 2048)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_scanned_pdf_is_stored_with_needs_ocr_status(client: TestClient) -> None:
    document = pymupdf.open()
    document.new_page()
    data = document.tobytes()
    document.close()
    response = _upload(client, "escaneo.pdf", data)
    assert response.status_code == 201
    assert response.json()["extraction_status"] == "needs_ocr"


def test_missing_file_field_returns_422(client: TestClient) -> None:
    assert client.post("/documents").status_code == 422


def test_unknown_and_malformed_ids(client: TestClient) -> None:
    unknown = "doc_" + "0" * 24
    response = client.get(f"/documents/{unknown}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert client.get(f"/documents/{unknown}/download").status_code == 404
    assert client.get("/documents/..%2F..%2Fsecret").status_code in (404, 422)
    assert client.get("/documents/no-es-un-id").status_code == 422


def test_download_when_original_was_removed(client: TestClient, settings: Settings) -> None:
    doc_id = _upload(client, "muestra.txt", _fixture("muestra.txt")).json()["doc_id"]
    for path in _originals(settings):
        path.unlink()
    response = client.get(f"/documents/{doc_id}/download")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "original_missing"


def test_metadata_persists_across_app_instances(settings: Settings) -> None:
    doc_id = _upload(admin_client(settings), "muestra.docx", _fixture("muestra.docx")).json()["doc_id"]
    again = admin_client(settings)
    assert again.get(f"/documents/{doc_id}").status_code == 200


def test_openapi_documents_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/documents", "/documents/{doc_id}", "/documents/{doc_id}/download"} <= set(paths)
    assert "post" in paths["/documents"] and "get" in paths["/documents"]
