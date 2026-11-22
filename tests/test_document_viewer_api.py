"""Texto completo y vista previa PDF para el visor (DOC-28)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from backend.app.config import Settings
from tests.auth_helpers import admin_client, anonymous_client

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(tmp_path / "data")


def _upload(client, name: str, data: bytes | None = None) -> dict:
    response = client.post("/documents", files={"file": (name, data if data is not None else (FIXTURES / name).read_bytes())})
    assert response.status_code == 201, response.text
    return response.json()


LONG = " ".join(f"palabra{i}" for i in range(700)) + "\n\nFinal del documento con <script>alert(1)</script> literal."


@pytest.mark.parametrize("overlap", [30, 0])
def test_text_matches_chunk_offsets(settings: Settings, overlap: int) -> None:
    client = admin_client(replace(settings, chunk_overlap=overlap))
    doc = _upload(client, "largo.txt", LONG.encode("utf-8"))
    body = client.get(f"/documents/{doc['doc_id']}/text").json()
    text = body["text"]
    chunks = client.get(f"/documents/{doc['doc_id']}/chunks").json()["items"]
    assert len(chunks) == len(body["chunks"]) >= 4
    for full, pos in zip(chunks, body["chunks"]):
        assert text[pos["char_start"]:pos["char_end"]] == full["text"]
    assert text.startswith("palabra0") and text.endswith("literal.")
    # el texto se entrega como dato, sin interpretar ni escapar
    assert "<script>alert(1)</script>" in text


def test_text_of_pdf_keeps_pages(settings: Settings) -> None:
    client = admin_client(settings)
    doc = _upload(client, "muestra.pdf")
    body = client.get(f"/documents/{doc['doc_id']}/text").json()
    assert body["extraction_status"] == "extracted"
    assert body["chunks"][0]["page_start"] == 1
    assert "storage" not in str(body) and "originals" not in str(body)


def test_pdf_preview_is_inline_and_same_origin_only(settings: Settings) -> None:
    client = admin_client(settings)
    doc = _upload(client, "muestra.pdf")
    response = client.get(f"/documents/{doc['doc_id']}/content")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content.startswith(b"%PDF")


@pytest.mark.parametrize("name", ["muestra.docx", "muestra.txt"])
def test_preview_rejects_non_pdf(settings: Settings, name: str) -> None:
    client = admin_client(settings)
    doc = _upload(client, name)
    response = client.get(f"/documents/{doc['doc_id']}/content")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "preview_unavailable"


def test_viewer_endpoints_require_session(settings: Settings) -> None:
    doc = _upload(admin_client(settings), "muestra.pdf")
    anon = anonymous_client(settings)
    for suffix in ("text", "content"):
        assert anon.get(f"/documents/{doc['doc_id']}/{suffix}").status_code == 401


def test_viewer_endpoints_404(settings: Settings) -> None:
    client = admin_client(settings)
    assert client.get("/documents/doc_000000000000000000000000/text").status_code in (404, 422)
    assert client.get("/documents/../etc/content").status_code == 404
