"""Dependencias FastAPI de sesión, rol y CSRF (DOC-25).

* ``require_user``: sesión válida de Usuario o Administrador (401 si no).
* ``require_admin``: sesión de Administrador (403 si es Usuario).
* ``require_admin_mutation``: Administrador + token CSRF + origen válido.

El servidor comprueba los permisos en cada endpoint; la interfaz web solo
oculta lo que el rol no puede hacer.
"""

from __future__ import annotations

import hmac
from typing import Optional

from fastapi import Depends, Request

from backend.app.api.errors import ApiError
from backend.app.config import Settings

from .sessions import LoginRateLimiter, Session, SessionStore

SESSION_COOKIE = "docusearch_session"
CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def get_session_store(request: Request) -> SessionStore:
    store = getattr(request.app.state, "sessions", None)
    if store is None:
        settings: Settings = request.app.state.settings
        store = SessionStore(
            idle_seconds=settings.session_idle_seconds, absolute_seconds=settings.session_absolute_seconds
        )
        request.app.state.sessions = store
    return store


def get_login_limiter(request: Request) -> LoginRateLimiter:
    limiter = getattr(request.app.state, "login_limiter", None)
    if limiter is None:
        settings: Settings = request.app.state.settings
        limiter = LoginRateLimiter(
            max_failures=settings.login_max_failures, window_seconds=settings.login_window_seconds
        )
        request.app.state.login_limiter = limiter
    return limiter


def optional_session(request: Request, store: SessionStore = Depends(get_session_store)) -> Optional[Session]:
    return store.get(request.cookies.get(SESSION_COOKIE))


def require_user(session: Optional[Session] = Depends(optional_session)) -> Session:
    if session is None:
        raise ApiError(401, "not_authenticated", "inicie sesión para continuar (o la sesión expiró)")
    return session


def require_admin(session: Session = Depends(require_user)) -> Session:
    if not session.is_admin:
        raise ApiError(403, "forbidden", "esta acción requiere el rol de Administrador")
    return session


def _expected_origin(request: Request) -> str:
    host = request.headers.get("host", "")
    return f"{request.url.scheme}://{host}".lower()


def check_same_origin(request: Request) -> None:
    """Rechaza peticiones de otro sitio (Origin / Sec-Fetch-Site)."""
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise ApiError(403, "csrf_failed", "petición de otro sitio rechazada")
    origin = request.headers.get("origin")
    if origin is not None and origin.lower() != _expected_origin(request):
        raise ApiError(403, "csrf_failed", "origen de la petición no permitido")


def check_csrf(request: Request, session: Session) -> None:
    if request.method not in UNSAFE_METHODS:
        return
    check_same_origin(request)
    sent = request.headers.get(CSRF_HEADER, "")
    if not sent or not hmac.compare_digest(sent.encode(), session.csrf_token.encode()):
        raise ApiError(403, "csrf_failed", "falta el token CSRF o no es válido; recargue la página")


def require_user_mutation(request: Request, session: Session = Depends(require_user)) -> Session:
    check_csrf(request, session)
    return session


def require_admin_mutation(request: Request, session: Session = Depends(require_admin)) -> Session:
    check_csrf(request, session)
    return session
