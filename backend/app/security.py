"""Cabeceras de seguridad y filtros previos al cuerpo de la petición (DOC-32).

Middleware ASGI puro (sin leer el cuerpo):

* **Antes del cuerpo**: las mutaciones (`POST`, `PUT`, `PATCH`, `DELETE`) a
  rutas privadas sin sesión válida se rechazan con 401 sin leer el cuerpo;
  si la sesión no es de Administrador donde se requiere, 403. Así una
  persona anónima no puede hacer que el servidor reciba y guarde en disco
  una carga multipart de cientos de MB. Los permisos se vuelven a comprobar
  en cada endpoint (esto es una primera barrera, no la única).
* **Tamaño**: las mutaciones deben declarar `Content-Length` (411 si no) y no
  superar el máximo (413). uvicorn/h11 no aceptan más bytes que los
  declarados.
* **Cabeceras**: CSP restrictiva para la aplicación, `nosniff`,
  `Referrer-Policy: no-referrer`, `X-Frame-Options`, `Permissions-Policy`,
  aislamiento de origen y `Cache-Control: no-store` en respuestas privadas.
  Una respuesta que ya trae su propia CSP (vista previa PDF) la conserva.
  `/docs` y `/redoc` (Swagger, que carga recursos de jsDelivr) quedan sin CSP.
"""

from __future__ import annotations

import json
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.auth.dependencies import SESSION_COOKIE, get_session_store

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
JSON_BODY_LIMIT = 1024 * 1024
PRIVATE_PREFIXES = ("/documents", "/admin", "/auth/logout", "/ask")
ADMIN_PREFIXES = ("/documents", "/admin")
NO_STORE_PREFIXES = ("/documents", "/search", "/auth", "/admin", "/ask")
DOCS_PATHS = ("/docs", "/redoc")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; frame-src 'self'; object-src 'none'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
BASE_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"referrer-policy": b"no-referrer",
    b"permissions-policy": b"camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    b"cross-origin-opener-policy": b"same-origin",
    b"cross-origin-resource-policy": b"same-origin",
}


def _cookie(headers: dict[bytes, bytes], name: str) -> str | None:
    raw = headers.get(b"cookie", b"").decode("latin-1")
    for part in raw.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return None


class SecurityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def _reject(self, send: Send, status: int, code: str, message: str) -> None:
        body = json.dumps({"error": {"code": code, "message": message}}, ensure_ascii=False).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
                (b"connection", b"close"),
                *BASE_HEADERS.items(),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET")
        headers = dict(scope.get("headers") or [])
        app_state: Any = scope["app"].state if "app" in scope else None

        if method in UNSAFE and app_state is not None:
            rejection = self._precheck(path, method, headers, app_state)
            if rejection is not None:
                await self._reject(send, *rejection)
                return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                current = dict((k.lower(), v) for k, v in message.get("headers", []))
                extra: list[tuple[bytes, bytes]] = [(k, v) for k, v in BASE_HEADERS.items() if k not in current]
                if not path.startswith(DOCS_PATHS):
                    if b"content-security-policy" not in current:
                        extra.append((b"content-security-policy", CSP.encode()))
                    if b"x-frame-options" not in current:
                        extra.append((b"x-frame-options", b"DENY"))
                if path.startswith(NO_STORE_PREFIXES) and b"cache-control" not in current:
                    extra.append((b"cache-control", b"no-store"))
                message = {**message, "headers": list(message.get("headers", [])) + extra}
            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _precheck(self, path: str, method: str, headers: dict[bytes, bytes], state: Any) -> tuple[int, str, str] | None:
        if not path.startswith(PRIVATE_PREFIXES):
            limit = JSON_BODY_LIMIT
        else:
            session = None
            store = getattr(state, "sessions", None)
            if store is None:
                store = _store_from_state(state)
            session = store.get(_cookie(headers, SESSION_COOKIE))
            if session is None:
                return 401, "not_authenticated", "inicie sesión para continuar (o la sesión expiró)"
            if path.startswith(ADMIN_PREFIXES) and not session.is_admin:
                return 403, "forbidden", "esta acción requiere el rol de Administrador"
            settings = state.settings
            limit = settings.max_upload_bytes + 64 * 1024 if path == "/documents" else JSON_BODY_LIMIT
        if b"transfer-encoding" in headers and b"content-length" not in headers:
            return 411, "length_required", "la petición debe indicar Content-Length"
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                length = int(raw_length)
            except ValueError:
                return 400, "bad_request", "Content-Length inválido"
            if length > limit:
                return 413, "payload_too_large", f"la petición supera el máximo de {limit // (1024 * 1024) or 1} MB"
        return None


class _StateRequest:
    """Adaptador mínimo para reutilizar ``get_session_store`` fuera de FastAPI."""

    def __init__(self, state: Any) -> None:
        self.app = type("App", (), {"state": state})()


def _store_from_state(state: Any):
    return get_session_store(_StateRequest(state))  # type: ignore[arg-type]
