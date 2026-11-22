"""Servidor real y navegador para las pruebas E2E de la web (DOC-26/DOC-33).

Se ejecutan con ``DOCUSEARCH_TEST_BROWSER=1`` y Playwright instalado
(``python -m pip install -e ".[e2e]"`` y ``python -m playwright install
chromium``). ``DOCUSEARCH_E2E_CHANNEL=chrome`` usa el Chrome del sistema en
lugar del Chromium de Playwright. Los datos y las cuentas son temporales.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

if os.environ.get("DOCUSEARCH_TEST_BROWSER") != "1":
    pytest.skip("pruebas de navegador: defina DOCUSEARCH_TEST_BROWSER=1", allow_module_level=True)

playwright_api = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

from backend.app.config import Settings  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from tests.auth_helpers import ADMIN_PASSWORD, ADMIN_USER, READER_PASSWORD, READER_USER, with_test_accounts  # noqa: E402

ARTIFACTS = Path(os.environ.get("DOCUSEARCH_E2E_ARTIFACTS", "e2e-artifacts"))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LiveServer:
    def __init__(self, settings: Settings, **app_kwargs) -> None:
        self.settings = settings
        self.app = create_app(settings, **app_kwargs)
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        config = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> "LiveServer":
        self.thread.start()
        deadline = time.time() + 20
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("el servidor de pruebas no arrancó")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


@pytest.fixture()
def live_server(tmp_path: Path, request) -> Iterator[LiveServer]:
    settings = with_test_accounts(Settings.from_env(tmp_path / "data"))
    factory = getattr(request, "param", None)
    kwargs = {"encoder_factory": factory} if factory else {}
    with LiveServer(settings, **kwargs) as server:
        yield server


@pytest.fixture(scope="session")
def browser() -> Iterator[object]:
    channel = os.environ.get("DOCUSEARCH_E2E_CHANNEL") or None
    with playwright_api.sync_playwright() as pw:
        instance = pw.chromium.launch(channel=channel)
        yield instance
        instance.close()


@pytest.fixture()
def page(browser, request) -> Iterator[object]:
    context = browser.new_context(viewport={"width": 1280, "height": 800}, locale="es-MX")
    page = context.new_page()
    page.console_errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda exc: page.console_errors.append(str(exc)))  # type: ignore[attr-defined]
    page.set_default_timeout(15_000)
    yield page
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    failed = getattr(request.node, "rep_call", None)
    if failed is not None and failed.failed:
        page.screenshot(path=str(ARTIFACTS / f"{request.node.name}-fallo.png"), full_page=True)
    context.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


def login(page, server: LiveServer, role: str = "admin") -> None:
    username, password = (ADMIN_USER, ADMIN_PASSWORD) if role == "admin" else (READER_USER, READER_PASSWORD)
    page.goto(f"{server.url}/#/login")
    page.get_by_label("Usuario").fill(username)
    page.get_by_label("Contraseña").fill(password)
    page.get_by_role("button", name="Iniciar sesión").click()
    page.get_by_text("Sesión:").wait_for()


def save_evidence(page, name: str) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ARTIFACTS / f"{name}.png"), full_page=True)


CONTRAST_JS = """
(selectors) => {
  const lum = (rgb) => {
    const [r, g, b] = rgb.match(/\\d+(\\.\\d+)?/g).slice(0, 3).map(Number).map((v) => {
      v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const bg = (el) => {
    for (let n = el; n; n = n.parentElement) {
      const c = getComputedStyle(n).backgroundColor;
      if (c && !c.endsWith(", 0)") && c !== "transparent") return c;
    }
    return "rgb(255, 255, 255)";
  };
  const out = [];
  for (const sel of selectors) {
    for (const el of document.querySelectorAll(sel)) {
      if (!el.offsetParent && el.tagName !== "BODY") continue;
      const fg = getComputedStyle(el).color, back = bg(el);
      const [a, b] = [lum(fg), lum(back)].sort((x, y) => y - x);
      out.push({ sel, ratio: (a + 0.05) / (b + 0.05), text: (el.textContent || "").trim().slice(0, 40) });
    }
  }
  return out;
}
"""


def contrast_ratios(page, selectors: list[str]) -> list[dict]:
    return page.evaluate(CONTRAST_JS, selectors)
