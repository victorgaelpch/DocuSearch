"""Capturas de la demostración para la documentación (DOC-35).

Recorre la demostración sintética (`demo/documentos`) y guarda capturas en
el directorio de evidencias (``DOCUSEARCH_E2E_ARTIFACTS``). Las de
`docs/capturas/` se generaron con esta prueba; para regenerarlas:

    $env:DOCUSEARCH_TEST_BROWSER = "1"; $env:DOCUSEARCH_E2E_ARTIFACTS = "docs/capturas"
    python -m pytest -q tests/e2e/test_web_capturas.py

Solo usa BM25: no se capturan resultados semánticos o híbridos porque las
pruebas E2E usan un codificador de prueba y no el modelo real.
"""

from __future__ import annotations

from pathlib import Path

from tests.e2e.conftest import login, save_evidence

DEMO = Path(__file__).resolve().parents[2] / "demo" / "documentos"


def test_capturas_de_la_demostracion(page, live_server) -> None:
    page.goto(live_server.url + "/")
    page.get_by_role("heading", level=1).wait_for()
    save_evidence(page, "captura-01-inicio")
    page.goto(live_server.url + "/#/login")
    page.get_by_label("Usuario").wait_for()
    save_evidence(page, "captura-02-inicio-de-sesion")
    login(page, live_server)
    page.goto(live_server.url + "/#/documentos")
    files = [str(p) for p in sorted(DEMO.iterdir()) if p.suffix in {".pdf", ".docx", ".txt"}]
    page.get_by_label("Archivos PDF, DOCX o TXT").set_input_files(files)
    page.get_by_role("button", name="Cargar documentos").click()
    page.get_by_text(f"{len(files)} de {len(files)} documento(s) cargado(s)").wait_for()
    save_evidence(page, "captura-03-carga-y-listado")
    page.goto(live_server.url + "/#/buscar")
    page.get_by_label("Consulta en español").fill("acuíferos subterráneos")
    page.get_by_role("button", name="Buscar", exact=True).click()
    page.locator(".hit").first.wait_for()
    save_evidence(page, "captura-04-resultados-bm25")
    page.locator(".hit h3 a").first.click()
    page.locator(".doc-text mark").wait_for()
    save_evidence(page, "captura-05-visor-fragmento")
    page.goto(live_server.url + "/#/indices")
    page.locator("article.collection").first.get_by_role("button", name="Reindexar").click()
    page.locator(".job").first.locator(".job-status", has_text="Terminada").wait_for()
    save_evidence(page, "captura-06-panel-indices")
