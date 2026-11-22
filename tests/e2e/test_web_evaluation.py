"""Panel de evaluación en el navegador (DOC-36)."""

from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[2] / "evaluation" / "results"


def test_panel_shows_versioned_miracl_numbers(page, live_server) -> None:
    raw = json.loads((RESULTS / "miracl_es_dev.json").read_text(encoding="utf-8"))
    page.goto(live_server.url + "/#/evaluacion")
    section = page.locator("section.evaluation.primary")
    section.get_by_role("heading", name="MIRACL español (dev): 648 consultas con juicios humanos").wait_for()
    table = section.locator("table").first
    for method, label in (("bm25", "BM25"), ("hybrid", "Híbrida"), ("semantic", "Semántica"), ("tfidf", "TF-IDF")):
        row = table.locator("tbody tr", has=page.get_by_role("rowheader", name=label, exact=True))
        expected = f"{raw['summary'][method]['all']['ndcg@10']:.4f}"  # tal como está en el archivo (es-MX: punto)
        assert expected in row.text_content(), (method, expected)
    readings = section.locator(".readings").text_content()
    assert "Semántica no difiere de forma significativa de BM25 en nDCG@10" in readings
    assert "Híbrida supera BM25 en nDCG@10 de forma significativa" in readings
    assert section.locator(".bar-fill").count() == 4
    width = section.locator(".bar-fill").first.evaluate("el => el.getBoundingClientRect().width")
    assert width > 0
    assert "no es el corpus MIRACL completo" in section.text_content()
    assert "[object" not in page.locator("main").text_content()
    others = len([p for p in RESULTS.glob("*.json") if p.name != "catalogo.json"]) - 1
    assert page.locator("details.evaluation-more").count() == others
    page.locator("details.evaluation-more > summary").first.click()
    assert page.get_by_text("Resultado secundario").first.is_visible()
