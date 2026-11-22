"""Endurecimiento y pruebas adversariales de la aplicación web (DOC-32).

Datos sintéticos únicamente. Complementa test_auth.py (sesión, CSRF),
test_upload_validation.py (ZIP bomb, nombres, tipos) y
test_google_docs_import.py (SSRF).
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

import pytest

from backend.app.config import Settings
from tests.auth_helpers import ADMIN_PASSWORD, admin_client, anonymous_client, logged_client

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(tmp_path / "data")


def _upload(client, name: str, data: bytes):
    return client.post("/documents", files={"file": (name, data)})


# -- cabeceras -------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/assets/js/app.js", "/health", "/auth/me", "/documents", "/search?q=x&collection=wikipedia_es"])
def test_security_headers_everywhere(settings: Settings, path: str) -> None:
    response = admin_client(settings).get(path)
    h = response.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "no-referrer"
    assert h["x-frame-options"] == "DENY"
    assert "camera=()" in h["permissions-policy"]
    csp = h["content-security-policy"]
    for directive in ("default-src 'self'", "script-src 'self'", "object-src 'none'", "frame-ancestors 'none'", "base-uri 'none'"):
        assert directive in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp


@pytest.mark.parametrize("path", ["/documents", "/auth/me", "/search?q=x&collection=wikipedia_es"])
def test_private_responses_are_not_cached(settings: Settings, path: str) -> None:
    assert "no-store" in admin_client(settings).get(path).headers["cache-control"]


def test_pdf_preview_keeps_its_frame_policy(settings: Settings) -> None:
    client = admin_client(settings)
    doc = _upload(client, "muestra.pdf", (FIXTURES / "muestra.pdf").read_bytes()).json()
    headers = client.get(f"/documents/{doc['doc_id']}/content").headers
    assert headers["x-frame-options"] == "SAMEORIGIN"
    assert headers["content-security-policy"] == "frame-ancestors 'self'"


def test_swagger_docs_still_work(settings: Settings) -> None:
    response = anonymous_client(settings).get("/docs")
    assert response.status_code == 200 and "content-security-policy" not in response.headers


# -- rechazo antes de leer el cuerpo -------------------------------------------------

class _ExplodingStream:
    """Cuerpo que falla si alguien intenta leerlo."""

    def __iter__(self):
        raise AssertionError("el servidor leyó el cuerpo de una petición anónima")
        yield b""  # pragma: no cover


def test_anonymous_mutation_is_rejected_before_reading_body(settings: Settings) -> None:
    anon = anonymous_client(settings)
    response = anon.post(
        "/documents", content=_ExplodingStream(),
        headers={"content-type": "multipart/form-data; boundary=x", "content-length": str(500 * 1024 * 1024)},
    )
    assert response.status_code == 401 and response.json()["error"]["code"] == "not_authenticated"


def test_reader_upload_is_rejected_before_reading_body(settings: Settings) -> None:
    reader = logged_client(settings, role="user")
    response = reader.post("/documents", content=_ExplodingStream(), headers={"content-length": "1000"})
    assert response.status_code == 403


def test_declared_oversize_upload_is_rejected(settings: Settings) -> None:
    client = admin_client(settings)
    response = client.post("/documents", content=_ExplodingStream(), headers={"content-length": str(10**9)})
    assert response.status_code == 413 and response.json()["error"]["code"] == "payload_too_large"


def test_chunked_body_without_length_is_refused(settings: Settings) -> None:
    client = admin_client(settings)
    response = client.post("/documents", content=_ExplodingStream(), headers={"transfer-encoding": "chunked"})
    assert response.status_code == 411


def test_large_json_body_is_refused(settings: Settings) -> None:
    anon = anonymous_client(settings)
    response = anon.post("/auth/login", content=_ExplodingStream(), headers={"content-length": str(5 * 1024 * 1024), "content-type": "application/json"})
    assert response.status_code == 413


# -- XSS, traversal y nombres maliciosos ---------------------------------------------

XSS = '<img src=x onerror="alert(1)"><script>alert(2)</script>'


def test_html_in_titles_and_text_is_returned_as_data(settings: Settings) -> None:
    client = admin_client(settings)
    doc = _upload(client, "nota.txt", f"{XSS} contenido de prueba sobre volcanes".encode()).json()
    assert client.patch(f"/documents/{doc['doc_id']}", json={"title": XSS}).status_code == 200
    for path in (f"/documents/{doc['doc_id']}", "/documents", "/search?q=volcanes"):
        response = client.get(path)
        assert response.headers["content-type"].startswith("application/json")
        assert XSS in response.text.replace("\\u003c", "<").replace('\\"', '"')
    # la interfaz nunca interpreta HTML (ver test_web.py: sin innerHTML)


@pytest.mark.parametrize(
    "path",
    [
        "/documents/..%2F..%2Fmetadata.db",
        "/documents/doc_..%2F..%2Fetc/download",
        "/documents/%2e%2e/download",
        "/assets/..%2F..%2Fbackend%2Fapp%2Fconfig.py",
        "/assets/%252e%252e/pyproject.toml",
    ],
)
def test_traversal_attempts_are_rejected(settings: Settings, path: str) -> None:
    response = admin_client(settings).get(path)
    assert response.status_code in (404, 422)
    assert b"DOCUSEARCH" not in response.content and b"[project]" not in response.content


@pytest.mark.parametrize(
    "name",
    ["../../evil.txt", "..\\..\\evil.txt", "C:\\Windows\\evil.txt", "evil.txt\x00.pdf", "<script>.txt", "CON.txt", "a" * 400 + ".txt"],
)
def test_malicious_filenames_never_escape_storage(settings: Settings, name: str) -> None:
    client = admin_client(settings)
    response = _upload(client, name, "texto de prueba con nombre extraño".encode())
    if response.status_code == 201:
        body = response.json()
        assert "/" not in body["original_filename"] and "\\" not in body["original_filename"]
        assert "\x00" not in body["original_filename"]
        assert "storage_path" not in body and str(settings.paths.root) not in response.text
    else:
        assert response.status_code in (400, 415, 422)
    stray = [p for p in settings.paths.root.parent.rglob("evil*")]
    assert stray == [] or all(settings.paths.originals_dir in p.parents for p in stray)


def test_errors_do_not_reveal_filesystem_paths(settings: Settings) -> None:
    client = admin_client(settings)
    doc = _upload(client, "muestra.txt", (FIXTURES / "muestra.txt").read_bytes()).json()
    for original in settings.paths.originals_dir.rglob("*.txt"):
        original.unlink()
    response = client.get(f"/documents/{doc['doc_id']}/download")
    assert response.status_code == 404
    assert str(settings.paths.root) not in response.text and "originals" not in response.text


# -- contraseñas y registros -------------------------------------------------------

def test_password_never_appears_in_logs_or_responses(settings: Settings, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    client = anonymous_client(settings)
    wrong = client.post("/auth/login", json={"username": "admin", "password": "incorrecta-secreta-777"})
    ok = client.login("admin", ADMIN_PASSWORD)
    assert ok.status_code == 200
    for text in (wrong.text, ok.text, str(dict(ok.headers)), caplog.text):
        assert ADMIN_PASSWORD not in text and "incorrecta-secreta-777" not in text


# -- repositorio limpio ------------------------------------------------------------

def _tracked_files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git no disponible")
    return out.stdout.splitlines()


def test_no_secrets_or_private_data_tracked() -> None:
    files = _tracked_files()
    assert ".env" not in files and not any(f.endswith((".pem", ".key", ".db", ".sqlite", ".faiss")) for f in files)
    assert [f for f in files if f.startswith("data/")] == ["data/README.md"]
    secret = re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]")
    for name in files:
        path = ROOT / name
        if path.suffix in {".py", ".md", ".toml", ".yml", ".yaml", ".json", ".js", ".ps1", ".example", ".txt"} and path.is_file():
            assert not secret.search(path.read_text(encoding="utf-8", errors="ignore")), name
