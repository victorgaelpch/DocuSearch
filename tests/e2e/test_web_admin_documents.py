"""Editar y eliminar documentos desde la web (DOC-30)."""

from __future__ import annotations

from pathlib import Path

from tests.e2e.conftest import login, save_evidence

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _upload_and_open(page, server, name: str = "muestra.pdf", title: str = "Informe de prueba DocuSearch") -> None:
    login(page, server)
    page.goto(server.url + "/#/documentos")
    page.get_by_label("Archivos PDF, DOCX o TXT").set_input_files(str(FIXTURES / name))
    page.get_by_role("button", name="Cargar documentos").click()
    page.get_by_role("link", name=f"Abrir {title}").click()
    page.locator(".doc-text").wait_for()


def test_edit_title_description_and_tags(page, live_server) -> None:
    _upload_and_open(page, live_server)
    sha_before = page.locator(".meta-details dd code.wrap").text_content()
    page.get_by_role("button", name="Editar datos").click()
    assert page.get_by_label("Título").evaluate("el => el === document.activeElement")
    page.get_by_label("Título").fill("")
    page.get_by_role("button", name="Guardar cambios").click()
    page.get_by_text("El título no puede quedar vacío.").wait_for()
    page.get_by_label("Título").fill("Informe final de la práctica")
    page.get_by_label("Descripción").fill("Versión entregada al profesor.")
    page.get_by_label("Etiquetas").fill("pln, búsqueda")
    page.get_by_role("button", name="Guardar cambios").click()
    page.get_by_role("heading", level=1, name="Informe final de la práctica").wait_for()
    page.get_by_text("Cambios guardados.").wait_for()
    page.locator(".meta-details summary").click()
    meta = page.locator(".meta-details").text_content()
    assert "Versión entregada al profesor." in meta and "pln, búsqueda" in meta
    assert page.locator(".meta-details dd code.wrap").text_content() == sha_before
    page.get_by_role("link", name="Buscar").click()
    page.get_by_label("Consulta en español").fill("índice invertido")
    page.get_by_role("button", name="Buscar", exact=True).click()
    page.get_by_role("link", name="Informe final de la práctica").wait_for()


def test_delete_with_confirmation_removes_from_list_and_search(page, live_server) -> None:
    _upload_and_open(page, live_server)
    doc_url = page.url
    page.get_by_role("button", name="Eliminar").click()
    dialog = page.get_by_role("dialog", name="¿Eliminar este documento?")
    dialog.wait_for()
    assert "No se puede deshacer" in dialog.text_content()
    save_evidence(page, "doc30-confirmar-eliminacion")
    # cancelar no borra nada
    dialog.get_by_role("button", name="Cancelar").click()
    assert page.get_by_role("dialog").count() == 0
    page.get_by_role("button", name="Eliminar").click()
    page.get_by_role("dialog").get_by_role("button", name="Eliminar definitivamente").click()
    page.wait_for_url("**/#/documentos")
    page.get_by_text("Se eliminó «Informe de prueba DocuSearch»").wait_for()
    page.get_by_text("Aún no hay documentos").wait_for()
    page.goto(doc_url)
    page.get_by_text("El documento no existe o fue eliminado.").wait_for()
    page.goto(live_server.url + "/#/buscar?q=%C3%ADndice%20invertido&method=bm25&k=10&collection=user")
    page.get_by_role("heading", name="Esta colección no tiene documentos indexados").wait_for()


def test_reader_has_no_edit_or_delete_actions(page, live_server) -> None:
    _upload_and_open(page, live_server, "muestra.txt", "muestra")
    url = page.url
    page.get_by_role("button", name="Cerrar sesión").click()
    page.get_by_role("link", name="Iniciar sesión").first.wait_for()
    login(page, live_server, role="user")
    page.goto(url)
    page.locator(".doc-text").wait_for()
    assert page.get_by_role("button", name="Editar datos").count() == 0
    assert page.get_by_role("button", name="Eliminar").count() == 0
