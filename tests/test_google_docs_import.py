"""Importación de Google Docs públicos por enlace (DOC-22).

Las respuestas de Google se simulan; la prueba con red real es opcional
(``DOCUSEARCH_TEST_NETWORK=1``).
"""

from __future__ import annotations

import email.message
import io
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.documents import google_docs
from backend.app.documents.google_docs import (
    DOCX_MIME,
    RemoteImportError,
    _SafeRedirect,
    fetch_public_doc,
    filename_from_disposition,
    parse_google_doc_url,
)
from backend.app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"
DOC_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd"
URL = f"https://docs.google.com/document/d/{DOC_ID}/edit?usp=sharing"


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, headers: dict[str, str], url: str = "https://doc-0s-docs.googleusercontent.com/x") -> None:
        super().__init__(data)
        self.headers = email.message.Message()
        for key, value in headers.items():
            self.headers[key] = value
        self._url = url

    def geturl(self) -> str:
        return self._url


def _docx_response(data: bytes | None = None, **headers: str) -> FakeResponse:
    data = data if data is not None else (FIXTURES / "muestra.docx").read_bytes()
    base = {"Content-Type": DOCX_MIME, "Content-Disposition": "attachment; filename=\"Informe.docx\"; filename*=UTF-8''Informe%20de%20prueba%20%C3%B1.docx"}
    return FakeResponse(data, {**base, **headers})


def _opener(result):
    def open_url(request: urllib.request.Request, timeout: float):
        open_url.requests.append(request)
        if isinstance(result, BaseException):
            raise result
        return result

    open_url.requests = []
    return open_url


# --- URL --------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        URL,
        f"https://docs.google.com/document/d/{DOC_ID}",
        f"https://docs.google.com/document/u/1/d/{DOC_ID}/view",
        f"  https://DOCS.google.com/document/d/{DOC_ID}/edit#heading=h.1  ",
    ],
)
def test_parse_valid_urls(url: str) -> None:
    assert parse_google_doc_url(url) == DOC_ID


@pytest.mark.parametrize(
    "url",
    [
        "",
        f"http://docs.google.com/document/d/{DOC_ID}/edit",
        f"https://docs.google.com.evil.com/document/d/{DOC_ID}/edit",
        f"https://evil.com/document/d/{DOC_ID}",
        f"https://docs.google.com:8443/document/d/{DOC_ID}",
        f"https://docs.google.com/spreadsheets/d/{DOC_ID}/edit",
        "https://docs.google.com/document/d/corto/edit",
        "https://docs.google.com/document/d/../../etc/passwd",
        "file:///etc/passwd",
        "https://[::1/document/d/x",
    ],
)
def test_parse_rejects_other_urls(url: str) -> None:
    with pytest.raises(RemoteImportError) as info:
        parse_google_doc_url(url)
    assert info.value.code == "invalid_url" and info.value.status_code == 422


def test_filename_from_disposition() -> None:
    assert filename_from_disposition("attachment; filename*=UTF-8''Informe%20%C3%B1.docx", DOC_ID) == "Informe ñ.docx"
    assert filename_from_disposition('attachment; filename="Plan.docx"', DOC_ID) == "Plan.docx"
    assert filename_from_disposition('attachment; filename="Plan"', DOC_ID) == "Plan.docx"
    assert filename_from_disposition(None, DOC_ID) == f"google-doc-{DOC_ID}.docx"


# --- redirecciones (SSRF) ---------------------------------------------------


def _redirect(target: str):
    handler = _SafeRedirect()
    request = urllib.request.Request(google_docs.EXPORT_URL.format(doc_id=DOC_ID))
    return handler.redirect_request(request, None, 307, "Temporary Redirect", {}, target)


def test_redirect_policy() -> None:
    assert _redirect("https://doc-0s-docs.googleusercontent.com/export/abc").full_url.startswith("https://doc-0s")
    assert _redirect("https://docs.google.com/document/d/x/export").full_url.startswith("https://docs.google.com")
    with pytest.raises(RemoteImportError) as info:
        _redirect("https://accounts.google.com/ServiceLogin?continue=x")
    assert info.value.code == "not_public" and info.value.status_code == 403
    for target in ("https://evil.com/x", "http://doc-0s.googleusercontent.com/x", "https://googleusercontent.com.evil.com/x"):
        with pytest.raises(RemoteImportError) as info:
            _redirect(target)
        assert info.value.code == "remote_error"


# --- descarga ---------------------------------------------------------------


def test_fetch_success_builds_export_url() -> None:
    opener = _opener(_docx_response())
    remote = fetch_public_doc(URL, max_bytes=10_000_000, open_url=opener)
    assert opener.requests[0].full_url == f"https://docs.google.com/document/d/{DOC_ID}/export?format=docx"
    assert remote.filename == "Informe de prueba ñ.docx" and remote.data.startswith(b"PK")
    assert remote.source_uri == f"https://docs.google.com/document/d/{DOC_ID}/edit" and remote.doc_id == DOC_ID


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(google_docs.EXPORT_URL, code, "x", email.message.Message(), None)


@pytest.mark.parametrize(
    ("result", "code", "status"),
    [
        (_http_error(404), "not_found", 404),
        (_http_error(403), "not_public", 403),
        (_http_error(401), "not_public", 403),
        (_http_error(500), "remote_error", 502),
        (TimeoutError("lento"), "remote_timeout", 504),
        (urllib.error.URLError("sin DNS"), "remote_error", 502),
        (FakeResponse(b"<html>login</html>", {"Content-Type": "text/html; charset=utf-8"}), "not_public", 403),
        (FakeResponse(b"x", {"Content-Type": DOCX_MIME}, url="https://accounts.google.com/ServiceLogin"), "not_public", 403),
        (_docx_response(b"x" * 100, **{"Content-Length": "999999999"}), "file_too_large", 413),
        (FakeResponse(b"x" * 5000, {"Content-Type": DOCX_MIME}), "file_too_large", 413),
    ],
)
def test_fetch_errors(result, code: str, status: int) -> None:
    with pytest.raises(RemoteImportError) as info:
        fetch_public_doc(URL, max_bytes=4096, open_url=_opener(result))
    assert (info.value.code, info.value.status_code) == (code, status)


# --- API --------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: Path, lexical_pipeline) -> TestClient:
    return TestClient(create_app(Settings.from_env(tmp_path / "data")))


def _patch_fetch(client: TestClient, monkeypatch, result) -> None:
    client.get("/documents")  # crea el servicio
    service = client.app.state.document_service

    def fake(url, *, max_bytes):
        return fetch_public_doc(url, max_bytes=max_bytes, open_url=_opener(result))

    monkeypatch.setattr(service, "fetch_google_doc", fake)


def test_import_endpoint_creates_searchable_document(client: TestClient, monkeypatch) -> None:
    _patch_fetch(client, monkeypatch, _docx_response())
    response = client.post("/documents/import", json={"url": URL})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_type"] == "google_docs"
    assert body["source_uri"] == f"https://docs.google.com/document/d/{DOC_ID}/edit"
    assert body["original_filename"] == "Informe de prueba ñ.docx" and body["chunk_count"] >= 1
    assert body["metadata"]["google_doc_id"] == DOC_ID
    hits = client.get("/search", params={"q": "lematización"}).json()["results"]
    assert hits and hits[0]["doc_id"] == body["doc_id"]
    assert client.get(body["download_url"]).content.startswith(b"PK")
    listed = client.get(f"/documents/{body['doc_id']}").json()
    assert listed["source_type"] == "google_docs"

    _patch_fetch(client, monkeypatch, _docx_response())
    duplicate = client.post("/documents/import", json={"url": URL})
    assert duplicate.status_code == 409 and duplicate.json()["error"]["doc_id"] == body["doc_id"]


def test_import_endpoint_errors(client: TestClient, monkeypatch) -> None:
    bad = client.post("/documents/import", json={"url": "https://evil.com/document/d/x"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_url"
    assert client.post("/documents/import", json={}).status_code == 422
    _patch_fetch(client, monkeypatch, FakeResponse(b"<html/>", {"Content-Type": "text/html"}))
    private = client.post("/documents/import", json={"url": URL})
    assert private.status_code == 403 and private.json()["error"]["code"] == "not_public"
    _patch_fetch(client, monkeypatch, _docx_response(b"PK no es un docx de verdad"))
    corrupt = client.post("/documents/import", json={"url": URL})
    assert corrupt.status_code in (415, 422)
    assert client.get("/documents").json()["total"] == 0
    upload = client.post("/documents", files={"file": ("nota.txt", "hola mundo".encode())}).json()
    assert upload["source_type"] == "upload" and upload["source_uri"] is None


@pytest.mark.skipif(os.environ.get("DOCUSEARCH_TEST_NETWORK") != "1", reason="requiere red (DOCUSEARCH_TEST_NETWORK=1)")
def test_live_google_nonexistent_document_is_not_found() -> None:
    with pytest.raises(RemoteImportError) as info:
        fetch_public_doc(URL, max_bytes=10_000_000)
    assert info.value.code == "not_found"
