"""Recorrido completo en un navegador real con documentos sintéticos (DOC-33).

PDF, DOCX y TXT → extracción → búsqueda (BM25 e híbrida) → fragmento de
origen → edición → reindexación → eliminación → cierre de sesión.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.nlp.embeddings import HashingEncoder
from tests.e2e.conftest import login, save_evidence

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CASES = [
    ("muestra.pdf", "índice invertido", "Informe de prueba DocuSearch", "invertido"),
    ("muestra.docx", "lematización forma base", "Apuntes de prueba", "lematización"),
    ("muestra.txt", "embeddings significado oraciones", "muestra", "embeddings"),
]


def _search(page, server, query: str, method: str) -> None:
    page.goto(f"{server.url}/#/buscar")
    page.get_by_label("Consulta en español").fill(query)
    page.get_by_label("Método").select_option(method)
    page.get_by_role("button", name="Buscar", exact=True).click()
    page.locator(".hit").first.wait_for()


@pytest.mark.parametrize("live_server", [lambda: HashingEncoder(64)], indirect=True)
def test_full_journey_pdf_docx_txt(page, live_server) -> None:
    login(page, live_server)
    page.get_by_role("link", name="Documentos").click()
    page.get_by_label("Archivos PDF, DOCX o TXT").set_input_files([str(FIXTURES / name) for name, *_ in CASES])
    page.get_by_role("button", name="Cargar documentos").click()
    page.get_by_text("3 de 3 documento(s) cargado(s)").wait_for()

    for name, query, title, term in CASES:
        for method in ("bm25", "hybrid"):
            _search(page, live_server, query, method)
            first = page.locator(".hit").first
            assert first.locator("h3").text_content() == title, (name, method)
            assert name in first.locator(".hit-meta").text_content()
        first.locator("h3 a").click()
        mark = page.locator(".doc-text mark")
        mark.wait_for()
        assert term in mark.text_content().lower()
        if name.endswith(".pdf"):
            assert "páginas 1–2" in page.locator(".chunk-position").text_content()  # el fragmento abarca dos páginas
    save_evidence(page, "doc33-recorrido-origen")

    # editar y comprobar que la búsqueda refleja el nuevo título
    page.get_by_role("button", name="Editar datos").click()
    page.get_by_label("Título").fill("Notas de embeddings")
    page.get_by_role("button", name="Guardar cambios").click()
    page.get_by_role("heading", level=1, name="Notas de embeddings").wait_for()
    _search(page, live_server, "embeddings significado", "bm25")
    assert page.locator(".hit h3").first.text_content() == "Notas de embeddings"

    # reindexar desde el panel
    page.get_by_role("link", name="Índices").click()
    page.locator("article.collection").first.get_by_role("button", name="Reindexar").click()
    page.locator(".job").first.locator(".job-status", has_text="Terminada").wait_for()
    assert "3 documento(s) refragmentados" in page.locator(".job").first.text_content()

    # eliminar y comprobar que desaparece de la búsqueda
    _search(page, live_server, "embeddings significado", "bm25")
    page.locator(".hit h3 a").first.click()
    page.get_by_role("button", name="Eliminar").click()
    page.get_by_role("dialog").get_by_role("button", name="Eliminar definitivamente").click()
    page.get_by_text("Se eliminó «Notas de embeddings»").wait_for()
    page.goto(f"{live_server.url}/#/buscar?q=embeddings%20significado&method=bm25&k=10&collection=user")
    page.locator(".search-output .results, .search-output .empty").first.wait_for()
    assert "Notas de embeddings" not in page.locator(".search-output").text_content()

    page.get_by_role("button", name="Cerrar sesión").click()
    page.get_by_role("link", name="Iniciar sesión").first.wait_for()
    assert page.request.get(f"{live_server.url}/documents").status == 401
    assert page.console_errors == []
