"""Buscador web con los cuatro métodos, comparación y estados de error (DOC-29)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.app.nlp import embeddings
from backend.app.nlp.embeddings import EmbeddingUnavailableError, HashingEncoder
from tests.e2e.conftest import login, save_evidence

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
HASHING = pytest.mark.parametrize("live_server", [lambda: HashingEncoder(64)], indirect=True)


def _no_model():
    raise EmbeddingUnavailableError("Falta sentence-transformers (extra 'semantic')")


def _load_fixtures(page, server) -> None:
    login(page, server)
    page.goto(server.url + "/#/documentos")
    page.get_by_label("Archivos PDF, DOCX o TXT").set_input_files(
        [str(FIXTURES / n) for n in ("muestra.pdf", "muestra.docx", "muestra.txt")]
    )
    page.get_by_role("button", name="Cargar documentos").click()
    page.get_by_text("3 de 3 documento(s) cargado(s)").wait_for()


def _search(page, query: str, method: str | None = None, compare: bool = False) -> None:
    page.get_by_role("link", name="Buscar").click()
    page.get_by_label("Consulta en español").fill(query)
    if method:
        page.get_by_label("Método").select_option(method)
    if compare:
        page.get_by_label("Comparar con BM25").check()
    page.get_by_role("button", name="Buscar", exact=True).click()


@HASHING
def test_bm25_results_show_rank_score_page_and_open_source(page, live_server) -> None:
    _load_fixtures(page, live_server)
    _search(page, "índice invertido")
    page.locator(".hit").first.wait_for()
    assert "k=10" in page.url and "method=bm25" in page.url
    first = page.locator(".hit").first
    assert first.locator("h3").text_content() == "Informe de prueba DocuSearch"
    meta = first.locator(".hit-meta").text_content()
    assert "Posición 1" in meta and "Puntuación" in meta and "muestra.pdf" in meta and "página" in meta
    assert first.locator(".hit-snippet mark").count() >= 1  # términos resaltados
    assert "ms" in page.locator(".results-head p").text_content()
    save_evidence(page, "doc29-resultados-bm25")
    first.locator("h3 a").click()
    page.locator(".doc-text mark").wait_for()
    assert "chunk=" in page.url
    assert "invertido" in page.locator(".doc-text mark").text_content()


@HASHING
def test_hybrid_compared_with_bm25_keeps_query(page, live_server) -> None:
    _load_fixtures(page, live_server)
    _search(page, "lematización forma base", method="hybrid", compare=True)
    blocks = page.locator(".results")
    blocks.nth(1).wait_for()
    assert [blocks.nth(i).locator("h2").text_content() for i in range(2)] == ["Híbrida", "BM25"]
    assert page.get_by_label("Consulta en español").input_value() == "lematización forma base"
    assert page.get_by_label("Método").input_value() == "hybrid"
    page.locator(".score-help summary").click()
    help_text = page.locator(".score-help").text_content()
    assert "no se comparan entre sí" in help_text and "RRF" in help_text
    save_evidence(page, "doc29-comparacion")


@pytest.mark.parametrize("live_server", [_no_model], indirect=True)
def test_semantic_unavailable_is_explained(page, live_server) -> None:
    _load_fixtures(page, live_server)
    _search(page, "significado de las oraciones", method="semantic")
    page.get_by_text("no está disponible en este servidor").wait_for()
    assert page.get_by_text("use BM25, que funciona sin él").is_visible()


def test_empty_query_and_no_results(page, live_server) -> None:
    _load_fixtures(page, live_server)
    page.get_by_role("link", name="Buscar").click()
    page.get_by_role("button", name="Buscar", exact=True).click()
    assert page.locator("#q-error").text_content() == "Escriba una consulta."
    assert page.get_by_label("Consulta en español").get_attribute("aria-invalid") == "true"
    page.get_by_label("Consulta en español").fill("zzzqqq inexistente")
    page.get_by_role("button", name="Buscar", exact=True).click()
    page.get_by_role("heading", name="Sin resultados").wait_for()


def test_anonymous_searches_only_public_corpus(page, live_server) -> None:
    page.goto(live_server.url + "/#/buscar")
    page.get_by_label("Consulta en español").wait_for()
    options = page.get_by_label("Colección").locator("option").all_text_contents()
    assert options == ["Corpus de prueba: Wikipedia en español"]
    page.get_by_label("Consulta en español").fill("historia")
    page.get_by_role("button", name="Buscar", exact=True).click()
    page.get_by_role("heading", name="Esta colección no tiene documentos indexados").wait_for()
    # forzar collection=user por la URL no expone documentos privados
    page.goto(live_server.url + "/#/buscar?q=texto&collection=user")
    page.locator(".search-output").wait_for()
    assert page.get_by_label("Colección").input_value() == "wikipedia_es"


@pytest.mark.semantic_model
@pytest.mark.skipif(
    not (embeddings.semantic_available() and os.environ.get("DOCUSEARCH_TEST_SEMANTIC_MODEL") == "1"),
    reason="requiere el extra semantic y DOCUSEARCH_TEST_SEMANTIC_MODEL=1",
)
def test_real_model_paraphrase_from_the_browser(page, live_server, tmp_path: Path) -> None:
    login(page, live_server)
    page.goto(live_server.url + "/#/documentos")
    files = {
        "dengue.txt": "El dengue es una enfermedad viral transmitida por la picadura de mosquitos Aedes.",
        "volcanes.txt": "Los volcanes expulsan lava, ceniza y gases cuando el magma asciende a la superficie.",
    }
    paths = []
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
        paths.append(str(tmp_path / name))
    page.get_by_label("Archivos PDF, DOCX o TXT").set_input_files(paths)
    page.get_by_role("button", name="Cargar documentos").click()
    page.get_by_text("2 de 2 documento(s) cargado(s)").wait_for()
    _search(page, "infección que contagian los zancudos", method="semantic", compare=True)
    blocks = page.locator(".results")
    blocks.nth(1).wait_for(timeout=120_000)
    assert "dengue.txt" in blocks.nth(0).locator(".hit").first.text_content()
    assert blocks.nth(1).get_by_role("heading", name="Sin resultados").is_visible()  # BM25 no comparte palabras
