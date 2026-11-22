"""Navegación, sesión, errores y accesibilidad básica en un navegador real (DOC-26)."""

from __future__ import annotations

from tests.e2e.conftest import contrast_ratios, login, save_evidence


def test_home_loads_without_script_errors(page, live_server) -> None:
    page.goto(live_server.url + "/")
    page.get_by_role("heading", level=1, name="Busque dentro de sus documentos").wait_for()
    assert page.title() == "Inicio · DocuSearch"
    assert page.locator("html").get_attribute("lang") == "es"
    assert page.get_by_role("navigation", name="Secciones").is_visible()
    assert page.console_errors == []
    save_evidence(page, "doc26-inicio")


def test_skip_link_is_first_tab_stop(page, live_server) -> None:
    page.goto(live_server.url + "/")
    page.get_by_role("heading", level=1).wait_for()
    page.keyboard.press("Tab")
    focused = page.evaluate("document.activeElement.textContent")
    assert focused == "Saltar al contenido"
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement.id") == "main"
    # el enlace de salto no cambia de vista
    assert page.get_by_role("heading", level=1, name="Busque dentro de sus documentos").is_visible()


def test_login_errors_then_success_and_logout(page, live_server) -> None:
    page.goto(live_server.url + "/#/login")
    page.get_by_role("button", name="Iniciar sesión").click()
    alert = page.locator("#login-error")
    assert alert.text_content() == "Escriba el usuario y la contraseña."
    page.get_by_label("Usuario").fill("admin")
    page.get_by_label("Contraseña").fill("incorrecta-123456")
    page.get_by_role("button", name="Iniciar sesión").click()
    page.get_by_text("Usuario o contraseña incorrectos.").wait_for()
    # el campo de contraseña se vacía y recibe el foco
    assert page.get_by_label("Contraseña").input_value() == ""
    login(page, live_server)
    page.get_by_text("Sesión iniciada como").wait_for()
    cookies = {c["name"]: c for c in page.context.cookies()}
    assert cookies["docusearch_session"]["httpOnly"] is True
    assert page.evaluate("document.cookie") == ""  # JavaScript no ve la cookie
    assert page.evaluate("Object.keys(localStorage).length") == 0
    page.get_by_role("button", name="Cerrar sesión").click()
    page.get_by_role("link", name="Iniciar sesión").first.wait_for()
    assert page.request.get(live_server.url + "/documents").status == 401


def test_unknown_route_and_nav_state(page, live_server) -> None:
    page.goto(live_server.url + "/#/no-existe")
    page.get_by_role("heading", name="Esta página no existe").wait_for()
    page.goto(live_server.url + "/#/ayuda")
    page.get_by_role("heading", level=1, name="Ayuda").wait_for()
    current = page.locator('#nav-list a[aria-current="page"]')
    assert current.text_content() == "Ayuda"


def test_server_down_message(page, live_server) -> None:
    page.goto(live_server.url + "/")
    page.get_by_role("heading", level=1).wait_for()
    page.route("**/auth/me", lambda route: route.abort())
    page.reload()
    page.get_by_text("No hay conexión con el servidor de DocuSearch").wait_for()


def test_mobile_menu_toggle(page, live_server) -> None:
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(live_server.url + "/")
    toggle = page.get_by_role("button", name="Menú")
    assert toggle.get_attribute("aria-expanded") == "false"
    assert not page.get_by_role("link", name="Ayuda").is_visible()
    toggle.click()
    assert toggle.get_attribute("aria-expanded") == "true"
    page.get_by_role("link", name="Ayuda").click()
    page.get_by_role("heading", level=1, name="Ayuda").wait_for()
    assert toggle.get_attribute("aria-expanded") == "false"
    save_evidence(page, "doc26-movil-ayuda")


def test_text_contrast_is_at_least_aa(page, live_server) -> None:
    login(page, live_server)
    page.goto(live_server.url + "/#/ayuda")
    page.get_by_role("heading", level=1, name="Ayuda").wait_for()
    ratios = contrast_ratios(page, ["body", "h1", "h2", "p", "a", ".btn", ".session", ".footer p", "dd"])
    low = [r for r in ratios if r["ratio"] < 4.5]
    assert ratios and not low, low


def test_form_controls_have_labels(page, live_server) -> None:
    page.goto(live_server.url + "/#/login")
    page.get_by_label("Usuario").wait_for()
    unlabeled = page.evaluate(
        """() => [...document.querySelectorAll('input, select, textarea')]
             .filter((el) => el.type !== 'hidden' && !(el.labels && el.labels.length) && !el.getAttribute('aria-label'))
             .map((el) => el.outerHTML)"""
    )
    assert unlabeled == []
