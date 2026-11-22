"""CSP activa y contenido malicioso inofensivo en el navegador (DOC-32)."""

from __future__ import annotations

from pathlib import Path

from tests.e2e.conftest import login

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
XSS_TITLE = '<img src=x onerror="window.__xss=1"><svg onload="window.__xss=2">'

CSP_LISTENER = """
window.__cspViolations = [];
document.addEventListener('securitypolicyviolation', (e) => window.__cspViolations.push(e.violatedDirective + ' ' + e.blockedURI));
"""


def test_app_runs_under_csp_without_violations(page, live_server) -> None:
    page.add_init_script(CSP_LISTENER)
    response = page.goto(live_server.url + "/")
    assert "script-src 'self'" in response.headers["content-security-policy"]
    login(page, live_server)
    for route in ("#/documentos", "#/buscar", "#/indices", "#/ayuda"):
        page.goto(f"{live_server.url}/{route}")
        page.get_by_role("heading", level=1).wait_for()
    assert page.evaluate("window.__cspViolations") == []
    assert page.console_errors == []


def test_malicious_title_is_shown_as_text_everywhere(page, live_server) -> None:
    login(page, live_server)
    csrf = page.evaluate("fetch('/auth/me').then(r => r.json()).then(b => b.csrf_token)")
    upload = page.request.post(
        f"{live_server.url}/documents",
        multipart={"file": {"name": "nota.txt", "mimeType": "text/plain", "buffer": "Texto sobre volcanes activos.".encode()}},
        headers={"X-CSRF-Token": csrf},
    ).json()
    patched = page.request.patch(
        f"{live_server.url}/documents/{upload['doc_id']}", data={"title": XSS_TITLE}, headers={"X-CSRF-Token": csrf}
    )
    assert patched.status == 200
    page.goto(live_server.url + "/#/documentos")
    page.locator("tbody tr").first.wait_for()
    page.goto(f"{live_server.url}/#/documentos/{upload['doc_id']}")
    page.locator(".doc-text").wait_for()
    assert page.locator("h1").text_content() == XSS_TITLE
    page.goto(live_server.url + "/#/buscar?q=volcanes&method=bm25&k=10&collection=user")
    page.locator(".hit").first.wait_for()
    assert page.locator(".hit h3").first.text_content() == XSS_TITLE
    assert page.evaluate("window.__xss") is None
    assert page.locator("main img, main svg").count() == 0
    assert page.title().startswith("volcanes")


def test_cross_site_form_post_cannot_upload(page, live_server, tmp_path: Path) -> None:
    """Una página de otro origen intenta cargar un archivo con la sesión del Administrador."""
    login(page, live_server)
    attacker = tmp_path / "ataque.html"
    attacker.write_text(
        f"""<form id=f method=post enctype=multipart/form-data action="{live_server.url}/documents">
        <input type=hidden name=x value=1></form><script>document.getElementById('f').submit()</script>""",
        encoding="utf-8",
    )
    with page.expect_response(lambda r: r.url.endswith("/documents")) as info:
        page.goto(attacker.as_uri())
    assert info.value.status in (401, 403)  # sin cookie (SameSite=Strict) o sin CSRF
    assert page.request.get(f"{live_server.url}/documents").json()["total"] == 0
