"""Panel de índices: reindexar desde la web y ver el resultado real (DOC-31)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.nlp.embeddings import HashingEncoder
from tests.e2e.conftest import login, save_evidence

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
HASHING = pytest.mark.parametrize("live_server", [lambda: HashingEncoder(64)], indirect=True)


def _upload(page, server) -> None:
    login(page, server)
    page.goto(server.url + "/#/documentos")
    page.get_by_label("Archivos PDF, DOCX o TXT").set_input_files([str(FIXTURES / n) for n in ("muestra.pdf", "muestra.txt")])
    page.get_by_role("button", name="Cargar documentos").click()
    page.get_by_text("2 de 2 documento(s) cargado(s)").wait_for()


@HASHING
def test_admin_reindexes_and_syncs_semantic_from_panel(page, live_server) -> None:
    _upload(page, live_server)
    page.get_by_role("link", name="Índices").click()
    card = page.locator("article.collection").first
    card.get_by_text("Mis documentos").wait_for()
    assert "Sin construir" in card.text_content()
    version = card.locator("dd code").first.text_content()
    card.get_by_role("button", name="Reindexar").click()
    job = page.locator(".job").first
    job.locator(".job-status", has_text="Terminada").wait_for()
    text = job.text_content()
    assert "2 documento(s) refragmentados" in text and f"Versión del índice léxico: {version}" in text
    page.locator("article.collection").first.get_by_role("button", name="Sincronizar índice semántico").click()
    page.locator(".job").first.get_by_text("vector(es);").wait_for()
    page.locator("article.collection").first.get_by_text("Sincronizado").wait_for()
    main_text = page.locator("main").text_content()
    assert "null" not in main_text and "undefined" not in main_text and "BM25 y TF-IDF" in main_text
    save_evidence(page, "doc31-panel-indices")


def test_semantic_actions_disabled_without_model(page, live_server) -> None:
    _upload(page, live_server)
    page.goto(live_server.url + "/#/indices")
    card = page.locator("article.collection").first
    card.wait_for()
    if "No instalada" in card.text_content():
        assert card.get_by_role("button", name="Sincronizar índice semántico").is_disabled()
        assert page.get_by_text("La búsqueda semántica no está instalada").is_visible()


def test_panel_is_admin_only(page, live_server) -> None:
    login(page, live_server, role="user")
    assert page.get_by_role("link", name="Índices").count() == 0
    page.goto(live_server.url + "/#/indices")
    page.get_by_role("heading", name="Acceso restringido").wait_for()
