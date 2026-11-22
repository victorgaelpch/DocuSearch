"""Interfaz web servida por FastAPI: rutas, tipos MIME y reglas estáticas (DOC-26)."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
JS_FILES = sorted((FRONTEND / "assets" / "js").rglob("*.js"))


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings.from_env(tmp_path / "data")))


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/", "text/html"),
        ("/assets/css/app.css", "text/css"),
        ("/assets/js/app.js", "text/javascript"),
        ("/assets/js/views/index.js", "text/javascript"),
        ("/assets/favicon.svg", "image/svg+xml"),
    ],
)
def test_frontend_is_served_same_origin(client: TestClient, path: str, content_type: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)


def test_api_docs_and_health_are_preserved(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}
    assert "/" not in client.get("/openapi.json").json()["paths"]


def test_assets_do_not_allow_traversal(client: TestClient) -> None:
    for path in ["/assets/../../backend/app/config.py", "/assets/%2e%2e/%2e%2e/pyproject.toml"]:
        assert client.get(path).status_code == 404


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_index_structure_is_accessible() -> None:
    parser = _Collector()
    parser.feed((FRONTEND / "index.html").read_text(encoding="utf-8"))
    tags = parser.tags
    assert ("html", {"lang": "es"}) in tags
    assert any(t == "a" and a.get("class") == "skip-link" and a.get("href") == "#main" for t, a in tags)
    assert any(t == "main" and a.get("id") == "main" for t, a in tags)
    assert any(t == "nav" and a.get("aria-label") for t, a in tags)
    assert any(t == "meta" and a.get("name") == "viewport" for t, a in tags)
    scripts = [a for t, a in tags if t == "script"]
    assert scripts and all(a.get("src") and a.get("type") == "module" for a in scripts), "sin scripts en línea"


@pytest.mark.parametrize("path", JS_FILES + [FRONTEND / "index.html", FRONTEND / "assets" / "css" / "app.css"], ids=lambda p: p.name)
def test_no_external_resources_or_unsafe_dom(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    # docs.google.com solo aparece como texto para validar el enlace de origen, no se carga
    assert not re.search(r"https?://(?!127\.0\.0\.1|localhost|docs\.google\.com/)", text), "recurso externo"
    assert "innerHTML" not in text and "outerHTML =" not in text and "insertAdjacentHTML" not in text
    assert "document.write" not in text and "eval(" not in text
    assert "localStorage.setItem" not in text and "sessionStorage.setItem" not in text


def test_js_imports_resolve() -> None:
    for path in JS_FILES:
        for target in re.findall(r'from\s+"(\.[^"]+)"', path.read_text(encoding="utf-8")):
            assert (path.parent / target).resolve().is_file(), f"{path.name} importa {target}"
