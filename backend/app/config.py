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
        )
