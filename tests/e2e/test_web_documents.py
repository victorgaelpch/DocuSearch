"""Carga, listado y filtrado de documentos desde el navegador (DOC-27)."""

from __future__ import annotations

from pathlib import Path

from backend.app.documents.ocr import find_tessdata
from tests.e2e.conftest import login, save_evidence
from tests.synthetic import scanned_pdf

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _upload(page, *paths: Path) -> None:
    page.get_by_label("Archivos PDF, DOCX o TXT").set_input_files([str(p) for p in paths])
    page.get_by_role("button", name="Cargar documentos").click()


def test_admin_uploads_pdf_docx_txt_and_sees_them_listed(page, live_server) -> None:
    login(page, live_server)
    page.goto(live_server.url + "/#/documentos")
    page.get_by_text("Aún no hay documentos").wait_for()
    _upload(page, FIXTURES / "muestra.pdf", FIXTURES / "muestra.docx", FIXTURES / "muestra.txt")
    page.get_by_text("3 de 3 documento(s) cargado(s)").wait_for()
    log = page.locator(".results-log li")
    assert log.count() == 3
    assert all("texto extraído" in log.nth(i).text_content() for i in range(3))
    assert all("Identificador:" in log.nth(i).text_content() for i in range(3))
    assert "1 fragmento." in log.nth(0).text_content()
    rows = page.locator("tbody tr:not(.detail-row)")
    rows.first.wait_for()
    assert rows.count() == 3
    formats = sorted(rows.nth(i).locator("td").first.text_content() for i in range(3))
    assert formats == ["PDF", "Texto (TXT)", "Word (DOCX)"]
    # detalle con el doc_id real
    first = rows.first
    first.get_by_role("button").click()
    detail = page.locator(".detail-row:not([hidden])")
    doc_id = detail.locator("dd code").first.text_content()
    assert "200 palabras con traslape de 30" in detail.text_content()
    assert "undefined" not in page.locator("main").text_content()
    assert len(doc_id) > 10
    api = page.request.get(f"{live_server.url}/documents/{doc_id}")
    assert api.status == 200
    save_evidence(page, "doc27-listado")


def test_duplicate_and_invalid_files_show_clear_errors(page, live_server, tmp_path: Path) -> None:
    login(page, live_server)
    page.goto(live_server.url + "/#/documentos")
    _upload(page, FIXTURES / "muestra.txt")
    page.get_by_text("1 de 1 documento(s) cargado(s)").wait_for()
    bad = tmp_path / "programa.exe"
    bad.write_bytes(b"MZ\x00\x00binario")
    fake_pdf = tmp_path / "roto.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 esto no es un PDF valido")
    _upload(page, FIXTURES / "muestra.txt", bad, fake_pdf)
    page.get_by_text("0 de 3 documento(s) cargado(s)").wait_for()
    log = page.locator(".results-log li.log-error")
    texts = [log.nth(i).text_content() for i in range(log.count())]
    assert len(texts) == 3
    assert "muestra.txt: ya estaba cargado con el identificador" in texts[0]
    assert texts[1].startswith("programa.exe:")
    assert texts[2].startswith("roto.pdf:")
    # el formulario conserva la selección para reintentar
    assert page.get_by_label("Archivos PDF, DOCX o TXT").evaluate("el => el.files.length") == 3


def test_scanned_pdf_reports_ocr_result(page, live_server, tmp_path: Path) -> None:
    pdf = tmp_path / "escaneado.pdf"
    pdf.write_bytes(scanned_pdf(["La fotosíntesis transforma la luz solar en energía química para la planta."]))
    login(page, live_server)
    page.goto(live_server.url + "/#/documentos")
    _upload(page, pdf)
    page.get_by_text("1 de 1 documento(s) cargado(s)").wait_for()
    line = page.locator(".results-log li").first.text_content()
    if find_tessdata() is None:
        assert "pendiente de ocr" in line
    else:
        assert "texto extraído" in line


def test_filters_are_applied_by_the_server(page, live_server) -> None:
    login(page, live_server)
    page.goto(live_server.url + "/#/documentos")
    _upload(page, FIXTURES / "muestra.pdf", FIXTURES / "muestra.docx", FIXTURES / "muestra.txt")
    page.get_by_text("3 de 3 documento(s) cargado(s)").wait_for()
    page.get_by_label("Formato").select_option("pdf")
    page.wait_for_url("**/#/documentos?format=pdf")
    page.get_by_text("Mostrando 1–1 de 1").wait_for()
    page.get_by_label("Formato").select_option("")
    page.get_by_label("Nombre o título").fill("no-existe-zzz")
    page.get_by_role("button", name="Filtrar").click()
    page.get_by_text("Ningún documento coincide").wait_for()
    page.get_by_role("link", name="Quitar filtros").click()
    page.get_by_text("Mostrando 1–3 de 3").wait_for()


def test_reader_sees_list_without_upload_forms(page, live_server) -> None:
    login(page, live_server)
    page.goto(live_server.url + "/#/documentos")
    _upload(page, FIXTURES / "muestra.txt")
    page.get_by_text("1 de 1 documento(s) cargado(s)").wait_for()
    page.get_by_role("button", name="Cerrar sesión").click()
    page.get_by_role("link", name="Iniciar sesión").first.wait_for()
    login(page, live_server, role="user")
    page.goto(live_server.url + "/#/documentos")
    page.locator("tbody tr").first.wait_for()
    assert page.get_by_role("button", name="Cargar documentos").count() == 0
    assert page.get_by_text("Solo el Administrador puede cargarlos").is_visible()


def test_anonymous_is_sent_to_login(page, live_server) -> None:
    page.goto(live_server.url + "/#/documentos")
    page.wait_for_url("**/#/login?next=%2Fdocumentos")
    page.get_by_label("Usuario").wait_for()
    login(page, live_server)
