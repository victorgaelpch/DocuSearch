"""Uso completo con teclado: sesión, búsqueda y apertura del origen (DOC-33)."""

from __future__ import annotations

from pathlib import Path

from tests.auth_helpers import ADMIN_PASSWORD, ADMIN_USER
from tests.e2e.conftest import login

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _tab_until(page, predicate_js: str, limit: int = 40) -> None:
    for _ in range(limit):
        page.keyboard.press("Tab")
        if page.evaluate(predicate_js):
            return
    raise AssertionError(f"no se alcanzó con Tab: {predicate_js}")


def test_keyboard_only_login_search_and_open_result(page, live_server) -> None:
    # preparar datos con la sesión del Administrador y salir
    login(page, live_server)
    page.goto(live_server.url + "/#/documentos")
    page.get_by_label("Archivos PDF, DOCX o TXT").set_input_files(str(FIXTURES / "muestra.pdf"))
    page.get_by_role("button", name="Cargar documentos").click()
    page.get_by_text("1 de 1 documento(s) cargado(s)").wait_for()
    page.get_by_role("button", name="Cerrar sesión").click()
    page.get_by_role("link", name="Iniciar sesión").first.wait_for()

    page.goto(live_server.url + "/#/login")
    page.locator("#username").wait_for()
    _tab_until(page, "document.activeElement.id === 'username'")
    page.keyboard.type(ADMIN_USER)
    page.keyboard.press("Tab")
    page.keyboard.type(ADMIN_PASSWORD)
    page.keyboard.press("Enter")
    page.get_by_text("Sesión:").wait_for()

    _tab_until(page, "document.activeElement.textContent === 'Buscar' && document.activeElement.tagName === 'A'")
    page.keyboard.press("Enter")
    page.get_by_label("Consulta en español").wait_for()
    # el foco va al título de la vista; desde ahí se llega al campo de consulta
    _tab_until(page, "document.activeElement.id === 'q'")
    page.keyboard.type("pingüino cañón")
    page.keyboard.press("Enter")
    page.locator(".hit").first.wait_for()
    _tab_until(page, "document.activeElement.closest('.hit h3') !== null")
    page.keyboard.press("Enter")
    page.locator(".doc-text mark").wait_for()
    assert "pingüino" in page.locator(".doc-text mark").text_content()


def test_focus_is_visible_on_interactive_elements(page, live_server) -> None:
    page.goto(live_server.url + "/#/login")
    page.locator("#username").wait_for()
    for _ in range(6):
        page.keyboard.press("Tab")
        outline = page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
        tag = page.evaluate("document.activeElement.tagName")
        if tag in ("A", "BUTTON", "INPUT"):
            assert outline != "none", tag


def test_dialog_traps_focus_and_escape_cancels(page, live_server) -> None:
    login(page, live_server)
    page.goto(live_server.url + "/#/documentos")
    page.get_by_label("Archivos PDF, DOCX o TXT").set_input_files(str(FIXTURES / "muestra.txt"))
    page.get_by_role("button", name="Cargar documentos").click()
    page.get_by_role("link", name="Abrir muestra").click()
    page.locator(".doc-text").wait_for()
    page.get_by_role("button", name="Eliminar").focus()
    page.keyboard.press("Enter")
    page.get_by_role("dialog").wait_for()
    assert page.evaluate("document.activeElement.textContent") == "Cancelar"
    page.keyboard.press("Escape")
    assert page.get_by_role("dialog").count() == 0
    assert page.request.get(f"{live_server.url}/documents").json()["total"] == 1
