"""Autenticación local, roles, CSRF, expiración y límite de intentos (DOC-25)."""

from __future__ import annotations

import io
import re
from dataclasses import replace
from pathlib import Path

import pytest

from backend.app.auth.passwords import InvalidPasswordHashError, hash_password, verify_password
from backend.app.auth.sessions import LoginRateLimiter, Role, SessionStore
from backend.app.cli import main as cli_main
from backend.app.config import Settings
from backend.app.main import create_app
from tests.auth_helpers import (
    ADMIN_PASSWORD,
    ADMIN_USER,
    READER_PASSWORD,
    READER_USER,
    SessionClient,
    admin_client,
    anonymous_client,
    logged_client,
)

FIXTURES = Path(__file__).parent / "fixtures"
TXT = (FIXTURES / "muestra.txt").read_bytes()


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(tmp_path / "data")


def _upload(client, name: str = "muestra.txt", data: bytes = TXT):
    return client.post("/documents", files={"file": (name, data)})


# -- contraseñas -------------------------------------------------------------

def test_hash_roundtrip_and_salt() -> None:
    first, second = hash_password("una clave larga 123"), hash_password("una clave larga 123")
    assert first != second  # sal aleatoria
    assert first.startswith("scrypt$")
    assert verify_password("una clave larga 123", first)
    assert not verify_password("otra clave larga 123", first)
    assert not verify_password("", first)


def test_short_password_rejected() -> None:
    with pytest.raises(ValueError):
        hash_password("corta")


@pytest.mark.parametrize("bad", ["texto", "scrypt$1$8$1$AAAA$BBBB", "bcrypt$x$y$z$a$b", "scrypt$16384$8$1$###$###"])
def test_malformed_hash_fails_at_startup(tmp_path: Path, bad: str) -> None:
    with pytest.raises(InvalidPasswordHashError):
        replace(Settings.from_env(tmp_path), admin_password_hash=bad)


def test_settings_read_hash_from_env(tmp_path: Path, monkeypatch) -> None:
    encoded = hash_password("clave de entorno 2026")
    monkeypatch.setenv("DOCUSEARCH_ADMIN_PASSWORD_HASH", encoded)
    monkeypatch.setenv("DOCUSEARCH_SESSION_IDLE_MINUTES", "5")
    settings = Settings.from_env(tmp_path)
    assert settings.admin_password_hash == encoded and settings.auth_configured
    assert settings.session_idle_seconds == 300


def test_cli_hash_password_from_stdin(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("contraseña segura de prueba\n"))
    assert cli_main(["hash-password", "--stdin"]) == 0
    out = capsys.readouterr().out.strip()
    assert verify_password("contraseña segura de prueba", out)
    assert "contraseña segura" not in out


# -- sin cuentas: no hay administrador por defecto ---------------------------

def test_no_default_account(settings: Settings) -> None:
    client = SessionClient(create_app(settings))
    assert client.get("/auth/me").json() == {
        "authenticated": False, "auth_configured": False,
        "username": None, "role": None, "csrf_token": None, "expires_at": None,
    }
    for username, password in [("admin", "admin"), ("admin", ""), ("admin", "password1234")]:
        response = client.post("/auth/login", json={"username": username, "password": password or "x"})
        assert response.status_code == 401
    assert client.post("/auth/login", json={"username": "admin", "password": "x"}).json()["error"]["code"] == "auth_not_configured"
    assert client.get("/documents").status_code == 401


# -- acceso anónimo -------------------------------------------------------

PRIVATE_GETS = [
    "/documents",
    "/documents/{doc}",
    "/documents/{doc}/download",
    "/documents/{doc}/chunks",
    "/search?q=texto",
    "/search?q=texto&collection=user",
    "/search/index",
]


def test_anonymous_cannot_read_private_documents(settings: Settings) -> None:
    doc_id = _upload(admin_client(settings)).json()["doc_id"]
    anon = anonymous_client(settings)
    for template in PRIVATE_GETS:
        response = anon.get(template.format(doc=doc_id))
        assert response.status_code == 401, template
        assert response.json()["error"]["code"] == "not_authenticated"
        assert doc_id not in response.text


def test_anonymous_cannot_upload_or_import(settings: Settings) -> None:
    anon = anonymous_client(settings)
    assert _upload(anon).status_code == 401
    response = anon.post("/documents/import", json={"url": "https://docs.google.com/document/d/abc/edit"})
    assert response.status_code == 401


def test_public_corpus_search_stays_anonymous(settings: Settings) -> None:
    anon = anonymous_client(settings)
    response = anon.get("/search", params={"q": "historia", "collection": "wikipedia_es"})
    assert response.status_code == 200
    assert anon.get("/health").status_code == 200


# -- roles ------------------------------------------------------------------

def test_reader_can_consult_but_not_mutate(settings: Settings) -> None:
    doc_id = _upload(admin_client(settings)).json()["doc_id"]
    reader = logged_client(settings, role="user")
    me = reader.get("/auth/me").json()
    assert me["role"] == "user" and me["username"] == READER_USER
    assert reader.get("/documents").json()["total"] == 1
    assert reader.get(f"/documents/{doc_id}/download").status_code == 200
    assert reader.get("/search", params={"q": "embeddings"}).status_code == 200
    response = _upload(reader, "otro.txt", b"texto distinto para probar permisos")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_admin_session_shape_and_cookie(settings: Settings) -> None:
    client = SessionClient(create_app(_accounts(settings)))
    response = client.post("/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin" and body["csrf_token"] and body["expires_at"]
    cookie = response.headers["set-cookie"].lower()
    assert "docusearch_session=" in cookie
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert ADMIN_PASSWORD.lower() not in cookie
    assert response.headers["cache-control"] == "no-store"


def _accounts(settings: Settings) -> Settings:
    from tests.auth_helpers import with_test_accounts

    return with_test_accounts(settings)


# -- CSRF ------------------------------------------------------------------

def test_mutation_without_csrf_is_rejected(settings: Settings) -> None:
    client = admin_client(settings)
    token, client.csrf_token = client.csrf_token, None
    response = _upload(client)
    assert response.status_code == 403 and response.json()["error"]["code"] == "csrf_failed"
    response = client.post("/documents", files={"file": ("muestra.txt", TXT)}, headers={"X-CSRF-Token": "falso"})
    assert response.status_code == 403
    client.csrf_token = token
    assert _upload(client).status_code == 201


def test_cross_origin_mutation_is_rejected(settings: Settings) -> None:
    client = admin_client(settings)
    response = client.post("/documents", files={"file": ("muestra.txt", TXT)}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    response = client.post("/documents", files={"file": ("muestra.txt", TXT)}, headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
    same = client.post("/documents", files={"file": ("muestra.txt", TXT)}, headers={"Origin": "http://testserver"})
    assert same.status_code == 201


def test_login_from_other_origin_is_rejected(settings: Settings) -> None:
    client = anonymous_client(settings)
    response = client.post(
        "/auth/login",
        json={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


# -- logout, expiración y fijación -------------------------------------------

def test_logout_invalidates_session(settings: Settings) -> None:
    client = admin_client(settings)
    cookie = client.cookies.get("docusearch_session")
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/documents").status_code == 401
    # reutilizar la cookie anterior tampoco funciona
    client.cookies.set("docusearch_session", cookie)
    assert client.get("/documents").status_code == 401
    assert client.get("/auth/me").json()["authenticated"] is False


def test_logout_requires_csrf(settings: Settings) -> None:
    client = admin_client(settings)
    client.csrf_token = None
    assert client.post("/auth/logout").status_code == 403
    assert client.get("/documents").status_code == 200


def test_session_expires_after_inactivity(settings: Settings) -> None:
    client = admin_client(settings)
    now = [1_000_000.0]
    store = client.app.state.sessions
    store.clock = lambda: now[0]
    # la sesión creada con el reloj real se renueva con el reloj simulado
    store.revoke_all()
    assert client.login(ADMIN_USER, ADMIN_PASSWORD).status_code == 200
    now[0] += settings.session_idle_seconds - 1
    assert client.get("/documents").status_code == 200  # renueva
    now[0] += settings.session_idle_seconds - 1
    assert client.get("/documents").status_code == 200
    now[0] += settings.session_idle_seconds + 1
    response = client.get("/documents")
    assert response.status_code == 401 and response.json()["error"]["code"] == "not_authenticated"


def test_absolute_session_limit() -> None:
    now = [0.0]
    store = SessionStore(idle_seconds=100, absolute_seconds=250, clock=lambda: now[0])
    token, _ = store.create("admin", Role.ADMIN)
    for _ in range(2):
        now[0] += 99
        assert store.get(token) is not None
    now[0] += 60  # 258 s desde la creación
    assert store.get(token) is None


def test_login_rotates_session_token(settings: Settings) -> None:
    client = admin_client(settings)
    first = client.cookies.get("docusearch_session")
    assert client.login(ADMIN_USER, ADMIN_PASSWORD).status_code == 200
    second = client.cookies.get("docusearch_session")
    assert first != second
    other = anonymous_client(settings)
    other.app.state.sessions = client.app.state.sessions
    other.cookies.set("docusearch_session", first)
    assert other.get("/documents").status_code == 401


# -- límite de intentos ------------------------------------------------------

def test_login_rate_limit(settings: Settings) -> None:
    client = anonymous_client(settings)
    for _ in range(settings.login_max_failures):
        response = client.post("/auth/login", json={"username": ADMIN_USER, "password": "incorrecta-123456"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"
    blocked = client.post("/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0


def test_unknown_user_and_wrong_password_look_the_same(settings: Settings) -> None:
    client = anonymous_client(settings)
    unknown = client.post("/auth/login", json={"username": "nadie", "password": READER_PASSWORD})
    wrong = client.post("/auth/login", json={"username": READER_USER, "password": "incorrecta-123456"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_rate_limiter_window() -> None:
    now = [0.0]
    limiter = LoginRateLimiter(max_failures=2, window_seconds=10, clock=lambda: now[0])
    limiter.failure("ip")
    limiter.failure("ip")
    assert limiter.retry_after("ip") > 0
    now[0] += 11
    assert limiter.retry_after("ip") == 0


# -- OpenAPI y secretos ------------------------------------------------------

def test_openapi_lists_auth_routes(settings: Settings) -> None:
    paths = anonymous_client(settings).get("/openapi.json").json()["paths"]
    assert {"/auth/login", "/auth/logout", "/auth/me"} <= set(paths)


REAL_HASH = re.compile(r"scrypt\$\d+\$\d+\$\d+\$[A-Za-z0-9+/]{20,}={0,2}\$[A-Za-z0-9+/]{40,}={0,2}")


def test_real_hash_pattern_detects_generated_hashes() -> None:
    assert REAL_HASH.search(hash_password("una clave larga 123"))
    assert not REAL_HASH.search("scrypt$16384$8$1$...$...")


def test_no_password_or_hash_in_repository() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in root.rglob("*"):
        if not path.is_file() or any(part in {".git", ".venv", "venv", "node_modules", "data"} for part in path.parts):
            continue
        if path.suffix not in {".py", ".md", ".toml", ".yml", ".yaml", ".json", ".js", ".html", ".ps1", ".example"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not REAL_HASH.search(text), f"hash de contraseña versionado en {path}"
