"""Configuración local de rutas de datos (DOC-02).

Separa tres zonas de almacenamiento que nunca se versionan:

* ``originals/``: archivos originales tal como se cargaron.
* ``metadata.db``: base SQLite con metadatos de ``Document`` y ``Chunk``.
* ``indexes/``: artefactos de índices (TF-IDF, BM25, FAISS) reconstruibles.

La raíz se puede cambiar con la variable de entorno ``DOCUSEARCH_DATA_DIR``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATA_DIR_ENV = "DOCUSEARCH_DATA_DIR"


@dataclass(frozen=True)
class DataPaths:
    """Rutas derivadas de una raíz de datos local."""

    root: Path

    @property
    def originals_dir(self) -> Path:
        return self.root / "originals"

    @property
    def metadata_db(self) -> Path:
        return self.root / "metadata.db"

    @property
    def indexes_dir(self) -> Path:
        return self.root / "indexes"

    def ensure(self) -> "DataPaths":
        """Crea los directorios necesarios (idempotente)."""
        for directory in (self.root, self.originals_dir, self.indexes_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return self


def get_data_paths(root: str | os.PathLike[str] | None = None) -> DataPaths:
    """Devuelve las rutas de datos; prioridad: argumento, entorno, ``data/``."""
    if root is None:
        root = os.environ.get(DATA_DIR_ENV) or DEFAULT_DATA_DIR
    return DataPaths(Path(root).resolve())


MAX_UPLOAD_MB_ENV = "DOCUSEARCH_MAX_UPLOAD_MB"
DEFAULT_MAX_UPLOAD_MB = 20
MAX_DOCX_UNCOMPRESSED_MB_ENV = "DOCUSEARCH_MAX_DOCX_UNCOMPRESSED_MB"
DEFAULT_MAX_DOCX_UNCOMPRESSED_MB = 200
CHUNK_SIZE_ENV = "DOCUSEARCH_CHUNK_SIZE"
CHUNK_OVERLAP_ENV = "DOCUSEARCH_CHUNK_OVERLAP"

# Autenticación local (DOC-25). Solo hashes; nunca contraseñas en claro.
ADMIN_USERNAME_ENV = "DOCUSEARCH_ADMIN_USERNAME"
ADMIN_PASSWORD_HASH_ENV = "DOCUSEARCH_ADMIN_PASSWORD_HASH"
USER_USERNAME_ENV = "DOCUSEARCH_USER_USERNAME"
USER_PASSWORD_HASH_ENV = "DOCUSEARCH_USER_PASSWORD_HASH"
SESSION_IDLE_MINUTES_ENV = "DOCUSEARCH_SESSION_IDLE_MINUTES"
SESSION_MAX_HOURS_ENV = "DOCUSEARCH_SESSION_MAX_HOURS"
COOKIE_SECURE_ENV = "DOCUSEARCH_COOKIE_SECURE"


def _positive_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} debe ser numérico, se recibió {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} debe ser mayor que 0")
    return value


@dataclass(frozen=True)
class Settings:
    """Configuración de la aplicación (DOC-04)."""

    paths: DataPaths
    max_upload_bytes: int
    max_docx_uncompressed_bytes: int
    chunk_size: int = 200
    chunk_overlap: int = 30
    # DOC-25: cuentas locales (sin hash configurado, la cuenta no existe)
    admin_username: str = "admin"
    admin_password_hash: Optional[str] = None
    user_username: str = "usuario"
    user_password_hash: Optional[str] = None
    session_idle_seconds: float = 30 * 60
    session_absolute_seconds: float = 8 * 3600
    cookie_secure: bool = False
    login_max_failures: int = 5
    login_window_seconds: float = 300

    def __post_init__(self) -> None:
        from backend.app.auth.passwords import parse_hash

        for value in (self.admin_password_hash, self.user_password_hash):
            if value:
                parse_hash(value)  # falla al arrancar si el hash está mal copiado
        if self.admin_password_hash and self.user_password_hash and self.admin_username == self.user_username:
            raise ValueError("las cuentas admin y usuario deben tener nombres distintos")

    @property
    def auth_configured(self) -> bool:
        return bool(self.admin_password_hash or self.user_password_hash)

    @classmethod
    def from_env(cls, data_dir: str | os.PathLike[str] | None = None) -> "Settings":
        upload_mb = _positive_float_env(MAX_UPLOAD_MB_ENV, DEFAULT_MAX_UPLOAD_MB)
        docx_mb = _positive_float_env(
            MAX_DOCX_UNCOMPRESSED_MB_ENV, DEFAULT_MAX_DOCX_UNCOMPRESSED_MB
        )
        return cls(
            paths=get_data_paths(data_dir),
            max_upload_bytes=int(upload_mb * 1024 * 1024),
            max_docx_uncompressed_bytes=int(docx_mb * 1024 * 1024),
            chunk_size=int(_positive_float_env(CHUNK_SIZE_ENV, 200)),
            chunk_overlap=int(os.environ.get(CHUNK_OVERLAP_ENV, "30") or 30),
            admin_username=(os.environ.get(ADMIN_USERNAME_ENV) or "admin").strip(),
            admin_password_hash=(os.environ.get(ADMIN_PASSWORD_HASH_ENV) or "").strip() or None,
            user_username=(os.environ.get(USER_USERNAME_ENV) or "usuario").strip(),
            user_password_hash=(os.environ.get(USER_PASSWORD_HASH_ENV) or "").strip() or None,
            session_idle_seconds=_positive_float_env(SESSION_IDLE_MINUTES_ENV, 30) * 60,
            session_absolute_seconds=_positive_float_env(SESSION_MAX_HOURS_ENV, 8) * 3600,
            cookie_secure=(os.environ.get(COOKIE_SECURE_ENV, "").strip().lower() in {"1", "true", "yes", "si", "sí"}),
        )
