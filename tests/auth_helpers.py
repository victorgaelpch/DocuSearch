"""Cuentas de prueba para la API protegida (DOC-25).

Las contraseñas se generan al azar en cada sesión de pruebas y nunca se
versionan. La protección NO se desactiva: los clientes inician sesión por
``/auth/login`` y envían el token CSRF como lo haría el navegador.
"""

from __future__ import annotations

import secrets
from dataclasses import replace
from functools import lru_cache

from fastapi.testclient import TestClient

from backend.app.auth.passwords import hash_password
from backend.app.config import Settings
from backend.app.main import create_app

ADMIN_USER = "admin"
READER_USER = "lector"
ADMIN_PASSWORD = "adm-" + secrets.token_urlsafe(18)
READER_PASSWORD = "usr-" + secrets.token_urlsafe(18)


@lru_cache(maxsize=None)
def _hashes() -> tuple[str, str]:
    return hash_password(ADMIN_PASSWORD), hash_password(READER_PASSWORD)


def with_test_accounts(settings: Settings) -> Settings:
    admin_hash, reader_hash = _hashes()
    return replace(
        settings,
        admin_username=ADMIN_USER,
        admin_password_hash=admin_hash,
        user_username=READER_USER,
        user_password_hash=reader_hash,
    )


class SessionClient(TestClient):
    """``TestClient`` que añade la cabecera CSRF de la sesión a las mutaciones."""

    csrf_token: str | None = None

    def request(self, method, url, *args, **kwargs):  # type: ignore[override]
        if self.csrf_token and method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            headers = dict(kwargs.pop("headers", None) or {})
            headers.setdefault("X-CSRF-Token", self.csrf_token)
            kwargs["headers"] = headers
        return super().request(method, url, *args, **kwargs)

    def login(self, username: str, password: str):
        response = self.post("/auth/login", json={"username": username, "password": password})
        if response.status_code == 200:
            self.csrf_token = response.json()["csrf_token"]
        return response


def logged_client(settings: Settings, *, role: str = "admin", **app_kwargs) -> SessionClient:
    client = SessionClient(create_app(with_test_accounts(settings), **app_kwargs))
    username, password = (ADMIN_USER, ADMIN_PASSWORD) if role == "admin" else (READER_USER, READER_PASSWORD)
    response = client.login(username, password)
    assert response.status_code == 200, response.text
    return client


def admin_client(settings: Settings, **app_kwargs) -> SessionClient:
    return logged_client(settings, role="admin", **app_kwargs)


def anonymous_client(settings: Settings, **app_kwargs) -> SessionClient:
    return SessionClient(create_app(with_test_accounts(settings), **app_kwargs))
