"""Sesiones en memoria y límite de intentos de inicio de sesión (DOC-25).

Las sesiones viven en el proceso: reiniciar el servidor las invalida todas.
El identificador de la cookie es aleatorio (256 bits) y en memoria solo se
guarda su SHA-256, de modo que un volcado del diccionario no permite
reutilizar cookies.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    ADMIN = "admin"
    USER = "user"


@dataclass
class Session:
    username: str
    role: Role
    csrf_token: str
    created_at: float
    last_seen: float
    expires_at: float

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN


def _key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionStore:
    """Sesiones con caducidad por inactividad y caducidad absoluta."""

    def __init__(
        self,
        *,
        idle_seconds: float,
        absolute_seconds: float,
        clock: Callable[[], float] = time.time,
        max_sessions: int = 1000,
    ) -> None:
        self.idle_seconds = idle_seconds
        self.absolute_seconds = absolute_seconds
        self.clock = clock
        self.max_sessions = max_sessions
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, username: str, role: Role) -> tuple[str, Session]:
        now = self.clock()
        token = secrets.token_urlsafe(32)
        session = Session(
            username=username,
            role=role,
            csrf_token=secrets.token_urlsafe(32),
            created_at=now,
            last_seen=now,
            expires_at=min(now + self.idle_seconds, now + self.absolute_seconds),
        )
        with self._lock:
            self._purge(now)
            if len(self._sessions) >= self.max_sessions:
                oldest = min(self._sessions, key=lambda k: self._sessions[k].last_seen)
                del self._sessions[oldest]
            self._sessions[_key(token)] = session
        return token, session

    def get(self, token: str | None) -> Session | None:
        """Sesión vigente para ``token`` (renueva la inactividad) o ``None``."""
        if not token or len(token) > 256:
            return None
        now = self.clock()
        key = _key(token)
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            if now >= session.expires_at:
                del self._sessions[key]
                return None
            session.last_seen = now
            session.expires_at = min(now + self.idle_seconds, session.created_at + self.absolute_seconds)
            return session

    def revoke(self, token: str | None) -> bool:
        if not token:
            return False
        with self._lock:
            return self._sessions.pop(_key(token), None) is not None

    def revoke_all(self) -> None:
        with self._lock:
            self._sessions.clear()

    def __len__(self) -> int:
        with self._lock:
            self._purge(self.clock())
            return len(self._sessions)

    def _purge(self, now: float) -> None:
        expired = [k for k, s in self._sessions.items() if now >= s.expires_at]
        for k in expired:
            del self._sessions[k]


class LoginRateLimiter:
    """Ventana deslizante de intentos fallidos por clave (IP del cliente)."""

    def __init__(self, *, max_failures: int, window_seconds: float, clock: Callable[[], float] = time.time) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float]:
        attempts = self._failures.setdefault(key, deque())
        while attempts and now - attempts[0] >= self.window_seconds:
            attempts.popleft()
        return attempts

    def retry_after(self, key: str) -> int:
        """Segundos de espera si la clave está bloqueada; 0 si puede intentar."""
        now = self.clock()
        with self._lock:
            attempts = self._recent(key, now)
            if len(attempts) < self.max_failures:
                return 0
            return max(1, int(attempts[0] + self.window_seconds - now) + 1)

    def failure(self, key: str) -> None:
        now = self.clock()
        with self._lock:
            self._recent(key, now).append(now)
            if len(self._failures) > 10_000:  # acota memoria ante muchas IPs
                for stale in [k for k, v in self._failures.items() if not v]:
                    del self._failures[stale]

    def success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
