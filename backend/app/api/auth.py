"""Endpoints de sesión (DOC-25): ``/auth/login``, ``/auth/logout``, ``/auth/me``."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.auth.dependencies import (
    SESSION_COOKIE,
    check_same_origin,
    get_login_limiter,
    get_session_store,
    optional_session,
    require_user_mutation,
)
from backend.app.auth.passwords import verify_password
from backend.app.auth.sessions import LoginRateLimiter, Role, Session, SessionStore
from backend.app.config import Settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class SessionOut(BaseModel):
    authenticated: bool
    auth_configured: bool
    username: Optional[str] = None
    role: Optional[Role] = None
    csrf_token: Optional[str] = None
    expires_at: Optional[datetime] = None


def _session_out(settings: Settings, session: Optional[Session]) -> SessionOut:
    if session is None:
        return SessionOut(authenticated=False, auth_configured=settings.auth_configured)
    return SessionOut(
        authenticated=True,
        auth_configured=True,
        username=session.username,
        role=session.role,
        csrf_token=session.csrf_token,
        expires_at=datetime.fromtimestamp(session.expires_at, tz=timezone.utc),
    )


def _accounts(settings: Settings) -> dict[str, tuple[str, Role]]:
    accounts: dict[str, tuple[str, Role]] = {}
    if settings.admin_password_hash:
        accounts[settings.admin_username] = (settings.admin_password_hash, Role.ADMIN)
    if settings.user_password_hash:
        accounts[settings.user_username] = (settings.user_password_hash, Role.USER)
    return accounts


@router.post(
    "/login",
    response_model=SessionOut,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
    summary="Iniciar sesión (cookie HttpOnly)",
)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    store: SessionStore = Depends(get_session_store),
    limiter: LoginRateLimiter = Depends(get_login_limiter),
) -> SessionOut:
    check_same_origin(request)
    settings: Settings = request.app.state.settings
    client_key = request.client.host if request.client else "desconocido"
    wait = limiter.retry_after(client_key)
    if wait:
        raise ApiError(
            429, "too_many_attempts", f"demasiados intentos fallidos; espere {wait} s", headers={"Retry-After": str(wait)}
        )
    accounts = _accounts(settings)
    if not accounts:
        raise ApiError(
            401, "auth_not_configured",
            "no hay cuentas configuradas: defina DOCUSEARCH_ADMIN_PASSWORD_HASH (ver docs/autenticacion.md)",
        )
    account = accounts.get(body.username.strip())
    # se verifica siempre un hash para no revelar por tiempo si el usuario existe
    encoded, role = account if account else (next(iter(accounts.values()))[0], None)
    valid = verify_password(body.password, encoded) and role is not None
    if not valid:
        limiter.failure(client_key)
        raise ApiError(401, "invalid_credentials", "usuario o contraseña incorrectos")
    limiter.success(client_key)
    old = request.cookies.get(SESSION_COOKIE)
    store.revoke(old)  # evita fijación de sesión
    token, session = store.create(body.username.strip(), role)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        path="/",
        max_age=int(settings.session_absolute_seconds),
    )
    response.headers["Cache-Control"] = "no-store"
    return _session_out(settings, session)


@router.post("/logout", status_code=204, summary="Cerrar sesión", responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}})
def logout(
    request: Request,
    response: Response,
    _: Session = Depends(require_user_mutation),
    store: SessionStore = Depends(get_session_store),
) -> Response:
    store.revoke(request.cookies.get(SESSION_COOKIE))
    settings: Settings = request.app.state.settings
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict", secure=settings.cookie_secure)
    return response


@router.get("/me", response_model=SessionOut, summary="Sesión actual y token CSRF")
def me(request: Request, response: Response, session: Optional[Session] = Depends(optional_session)) -> SessionOut:
    response.headers["Cache-Control"] = "no-store"
    return _session_out(request.app.state.settings, session)
