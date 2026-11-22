"""Preguntas con citas en el navegador (DOC-39). Proveedor simulado."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.nlp.embeddings import HashingEncoder
from tests.e2e.conftest import login, save_evidence
from tests.test_rag import FakeGenerator

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEMO = Path(__file__).resolve().parents[2] / "demo" / "documentos"
HASHING = pytest.mark.parametrize("live_server", [lambda: HashingEncoder(64)], indirect=True)


def _load_demo(page, server) -> None:
    login(page, server)
    page.goto(server.url + "/#/documentos")
    files = [str(p) for p in sorted(DEMO.iterdir()) if p.suffix in {".pdf", ".docx", ".txt"}]
    page.get_by_label("Archivos PDF, DOCX o TXT").set_input_files(files)
    page.get_by_role("button", name="Cargar documentos").click()
    page.get_by_text(f"{len(files)} de {len(files)} documento(s) cargado(s)").wait_for()


def _ask(page, server, question: str) -> None:
    page.goto(server.url + "/#/preguntar")
    page.get_by_label("Pregunta", exact=True).fill(question)
    page.get_by_label("Recuperación").select_option("bm25")
    page.get_by_role("button", name="Preguntar").click()


def test_not_configured_offers_search(page, live_server) -> None:
    _load_demo(page, live_server)
    page.get_by_role("link", name="Preguntar").click()
    page.get_by_text("No hay un modelo local configurado").wait_for()
    assert page.get_by_role("button", name="Preguntar").is_disabled()
    page.get_by_label("Pregunta", exact=True).fill("acuíferos subterráneos")
    page.get_by_role("button", name="Buscar en su lugar").click()
    page.locator(".hit").first.wait_for()
    assert "q=acu" in page.url


@HASHING
def test_answer_with_navigable_citations_and_safe_text(page, live_server) -> None:
    live_server.app.state.rag_generator = FakeGenerator(
        'Los acuíferos abastecen de agua potable a las ciudades [S1]. <img src=x onerror="window.__xss=1"> Fuente falsa [S8].'
    )
    _load_demo(page, live_server)
    _ask(page, live_server, "¿Qué abastece de agua potable a las ciudades?")
    answer = page.locator(".answer-text")
    answer.wait_for()
    assert '<img src=x onerror="window.__xss=1">' in answer.text_content()
    assert page.evaluate("window.__xss") is None and page.locator(".answer img").count() == 0
    assert "[S8]" not in answer.text_content()
    page.get_by_text("Se quitaron 1 cita(s)").wait_for()
    assert "verifique cada afirmación" in page.locator(".notice-warn").first.text_content()
    save_evidence(page, "doc39-respuesta-citada")
    cite = answer.locator("a.cite")
    assert cite.count() == 1 and cite.text_content() == "[S1]"
    page.get_by_role("button", name="Sí").click()
    page.get_by_text("Se registró la opinión").wait_for()
    cite.click()
    mark = page.locator(".doc-text mark")
    mark.wait_for()
    assert "acuíferos" in mark.text_content().lower()


@HASHING
def test_unsupported_answer_is_not_shown(page, live_server) -> None:
    live_server.app.state.rag_generator = FakeGenerator("El agua viene de la lluvia, según mi conocimiento general.")
    _load_demo(page, live_server)
    _ask(page, live_server, "¿De dónde sale el agua potable?")
    page.get_by_text("respondió sin citar ninguno de los fragmentos").wait_for()
    assert page.locator(".answer-text").count() == 0
    assert "conocimiento general" not in page.locator("main").text_content()
    page.locator(".score-help summary").click()
    assert page.locator(".sources li").count() >= 1


def test_reader_can_ask_and_anonymous_cannot(page, live_server) -> None:
    live_server.app.state.rag_generator = FakeGenerator("Acuíferos [S1].")
    _load_demo(page, live_server)
    page.get_by_role("button", name="Cerrar sesión").click()
    page.get_by_role("link", name="Iniciar sesión").first.wait_for()
    page.goto(live_server.url + "/#/preguntar")
    page.wait_for_url("**/#/login?next=%2Fpreguntar")
    login(page, live_server, role="user")
    _ask(page, live_server, "acuíferos subterráneos agua potable")
    page.locator(".answer-text").wait_for()
