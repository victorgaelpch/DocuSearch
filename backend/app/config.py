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
