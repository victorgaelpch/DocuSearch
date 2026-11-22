"""Visor: fragmento resaltado, navegación, PDF y contenido no confiable (DOC-28)."""

from __future__ import annotations

from pathlib import Path

from backend.app.documents import ocr as ocr_module
from tests.e2e.conftest import login, save_evidence
from tests.synthetic import scanned_pdf

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PAYLOAD = '<img src=x onerror="window.__xss=1"><script>window.__xss=2</script>'


def _upload_via_api(page, server, name: str, data: bytes) -> dict:
    csrf = page.evaluate("fetch('/auth/me').then(r => r.json()).then(b => b.csrf_token)")
    response = page.request.post(
        f"{server.url}/documents",
        multipart={"file": {"name": name, "mimeType": "application/octet-stream", "buffer": data}},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status == 201, response.text()
    return response.json()


def test_opens_requested_chunk_highlighted_and_navigates(page, live_server, tmp_path: Path) -> None:
    words = " ".join(f"término{i}" for i in range(650))
    text = f"Inicio del informe. {words} {PAYLOAD} cierre del informe."
    login(page, live_server)
    doc = _upload_via_api(page, live_server, "informe-largo.txt", text.encode("utf-8"))
    chunks = page.request.get(f"{live_server.url}/documents/{doc['doc_id']}/chunks").json()["items"]
    target = chunks[2]
    page.goto(f"{live_server.url}/#/documentos/{doc['doc_id']}?chunk={target['chunk_id']}")
    mark = page.locator(".doc-text mark")
    mark.wait_for()
    assert mark.text_content() == target["text"]
    assert page.locator(".chunk-position").text_content().startswith(f"Fragmento 3 de {len(chunks)}")
    assert mark.is_visible()  # se desplaza hasta el fragmento
    page.get_by_role("button", name="Fragmento siguiente").click()
    assert page.locator(".doc-text mark").text_content() == chunks[3]["text"]
    assert f"chunk={chunks[3]['chunk_id']}" in page.url
    # el contenido del documento no se interpreta como HTML
    assert page.evaluate("window.__xss") is None
    assert page.locator(".doc-text img, .doc-text script").count() == 0
    assert PAYLOAD in page.locator(".doc-text").text_content()
    save_evidence(page, "doc28-fragmento-resaltado")


def test_pdf_preview_opens_on_chunk_page(page, live_server) -> None:
    login(page, live_server)
    page.goto(live_server.url + "/#/documentos")
    page.get_by_label("Archivos PDF, DOCX o TXT").set_input_files(str(FIXTURES / "muestra.pdf"))
    page.get_by_role("button", name="Cargar documentos").click()
    page.get_by_role("link", name="Abrir Informe de prueba DocuSearch").click()
    page.locator(".doc-text").wait_for()
    assert "página" in page.locator(".chunk-position").text_content()
    with page.expect_response(lambda r: "/content" in r.url) as info:
        page.get_by_role("button", name="Vista del PDF").click()
    response = info.value
    assert response.status == 200 and response.headers["content-type"] == "application/pdf"
    frame = page.locator("iframe.pdf-frame")
    assert "#page=1" in frame.get_attribute("src")
    assert page.get_by_role("button", name="Vista del PDF").get_attribute("aria-pressed") == "true"
    assert page.locator("#panel-text").is_hidden()


def test_docx_has_no_pdf_preview(page, live_server) -> None:
    login(page, live_server)
    doc = _upload_via_api(page, live_server, "muestra.docx", (FIXTURES / "muestra.docx").read_bytes())
    page.goto(f"{live_server.url}/#/documentos/{doc['doc_id']}")
    page.locator(".doc-text").wait_for()
    assert page.get_by_role("button", name="Vista del PDF").count() == 0
    assert page.locator(".segmented").count() == 0
    assert "Sin paginación" in page.locator(".meta-details").text_content()


def test_scanned_pdf_without_ocr_shows_explicit_fallback(page, live_server, monkeypatch) -> None:
    monkeypatch.setenv("DOCUSEARCH_OCR", "off")
    monkeypatch.setattr(ocr_module, "_cached", None)
    login(page, live_server)
    doc = _upload_via_api(page, live_server, "escaneado.pdf", scanned_pdf(["Texto que solo existe como imagen."]))
    assert doc["extraction_status"] == "needs_ocr"
    page.goto(f"{live_server.url}/#/documentos/{doc['doc_id']}")
    page.get_by_text("Este PDF está escaneado").wait_for()
    assert page.get_by_role("button", name="Vista del PDF").get_attribute("aria-pressed") == "true"
    assert page.get_by_role("link", name="Descargar original").is_visible()


def test_missing_document_message(page, live_server) -> None:
    login(page, live_server)
    page.goto(f"{live_server.url}/#/documentos/doc_000000000000000000000000")
    page.get_by_role("heading", name="No se pudo abrir el documento").wait_for()
    assert page.get_by_text("El documento no existe o fue eliminado.").is_visible()
