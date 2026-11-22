"""Almacenamiento seguro de archivos originales (DOC-02).

Los originales se guardan con un nombre derivado del ``doc_id`` (nunca con el
nombre enviado por el usuario) dentro de ``originals/<colección>/``. Esto evita
path traversal y colisiones, y mantiene los originales fuera de rutas públicas.
La validación de tipo real y tamaño de carga corresponde a DOC-04.
"""

from __future__ import annotations

import os
import secrets
import re
import tempfile
from pathlib import Path, PurePosixPath

from .models import COLLECTION_PATTERN, DOC_ID_PATTERN

_EXTENSION_PATTERN = re.compile(r"^\.[a-z0-9]{1,10}$")


class UnsafePathError(ValueError):
    """La ruta solicitada sale del directorio de originales o es inválida."""


def build_storage_path(doc_id: str, extension: str, collection: str) -> str:
    """Ruta relativa POSIX (``<colección>/<doc_id><ext>``) para un original."""
    if not re.fullmatch(DOC_ID_PATTERN, doc_id):
        raise UnsafePathError(f"doc_id inválido: {doc_id!r}")
    if not re.fullmatch(COLLECTION_PATTERN, collection):
        raise UnsafePathError(f"colección inválida: {collection!r}")
    extension = extension.lower()
    if not _EXTENSION_PATTERN.fullmatch(extension):
        raise UnsafePathError(f"extensión inválida: {extension!r}")
    return f"{collection}/{doc_id}{extension}"


class OriginalStore:
    """Guarda y resuelve archivos originales bajo un directorio raíz."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()

    def resolve(self, storage_path: str) -> Path:
        """Convierte una ruta relativa en absoluta, rechazando escapes."""
        if not storage_path or "\\" in storage_path or "\x00" in storage_path:
            raise UnsafePathError("ruta de almacenamiento inválida")
        relative = PurePosixPath(storage_path)
        if relative.is_absolute() or ".." in relative.parts or ":" in storage_path:
            raise UnsafePathError("ruta de almacenamiento fuera del directorio permitido")
        candidate = (self.root / Path(*relative.parts)).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise UnsafePathError("ruta de almacenamiento fuera del directorio permitido")
        return candidate

    def save(self, storage_path: str, content: bytes) -> Path:
        """Escribe el original de forma atómica; no sobrescribe contenido distinto."""
        target = self.resolve(storage_path)
        if target.exists():
            if target.read_bytes() == content:
                return target
            raise FileExistsError(f"ya existe un original distinto en {storage_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return target

    def exists(self, storage_path: str) -> bool:
        return self.resolve(storage_path).is_file()

    def read(self, storage_path: str) -> bytes:
        return self.resolve(storage_path).read_bytes()

    def stage_delete(self, storage_path: str) -> Path | None:
        """Aparta el original (renombrado) para poder restaurarlo si algo falla (DOC-30)."""
        target = self.resolve(storage_path)
        if not target.is_file():
            return None
        staged = target.with_name(f".deleting-{secrets.token_hex(6)}-{target.name}")
        os.replace(target, staged)
        return staged

    def restore(self, staged: Path | None, storage_path: str) -> None:
        if staged is not None and staged.is_file():
            os.replace(staged, self.resolve(storage_path))

    @staticmethod
    def discard(staged: Path | None) -> bool:
        """Borra definitivamente un original apartado; ``False`` si no se pudo."""
        if staged is None:
            return True
        try:
            staged.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def delete(self, storage_path: str) -> bool:
        target = self.resolve(storage_path)
        if target.is_file():
            target.unlink()
            return True
        return False
