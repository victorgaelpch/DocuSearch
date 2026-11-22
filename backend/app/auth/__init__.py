"""Autenticación local monousuario (DOC-25).

Ver ``docs/autenticacion.md`` y ``docs/adr/0001-entrega-web-v1.md``.
"""

from .passwords import hash_password, verify_password
from .sessions import Role, Session, SessionStore

__all__ = ["Role", "Session", "SessionStore", "hash_password", "verify_password"]
