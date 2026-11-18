"""Persistencia de metadatos en SQLite para el MVP (DOC-02).

Se usa ``sqlite3`` de la biblioteca estándar: no requiere servidor, funciona en
Windows sin GPU y el archivo ``metadata.db`` es reproducible a partir de los
originales. Los índices de búsqueda NO se guardan aquí.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .models import Chunk, Document, ExtractionStatus, utc_now

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id             TEXT PRIMARY KEY,
    collection         TEXT NOT NULL,
    source_type        TEXT NOT NULL,
    title              TEXT NOT NULL,
    original_filename  TEXT NOT NULL,
    mime_type          TEXT NOT NULL,
    size_bytes         INTEGER NOT NULL CHECK (size_bytes >= 0),
    sha256             TEXT NOT NULL,
    storage_path       TEXT NOT NULL UNIQUE,
    source_uri         TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    extraction_status  TEXT NOT NULL,
    extraction_error   TEXT,
    page_count         INTEGER,
    language           TEXT NOT NULL,
    extra              TEXT NOT NULL DEFAULT '{}',
    UNIQUE (collection, sha256)
);

CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents (collection);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id    TEXT PRIMARY KEY,
    doc_id      TEXT NOT NULL REFERENCES documents (doc_id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL CHECK (ordinal >= 0),
    text        TEXT NOT NULL,
    char_start  INTEGER NOT NULL,
    char_end    INTEGER NOT NULL,
    page_start  INTEGER,
    page_end    INTEGER,
    word_count  INTEGER NOT NULL,
    UNIQUE (doc_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks (doc_id, ordinal);
"""

_DOCUMENT_COLUMNS = (
    "doc_id",
    "collection",
    "source_type",
    "title",
    "original_filename",
    "mime_type",
    "size_bytes",
    "sha256",
    "storage_path",
    "source_uri",
    "created_at",
    "updated_at",
    "extraction_status",
    "extraction_error",
    "page_count",
    "language",
    "extra",
)

_CHUNK_COLUMNS = (
    "chunk_id",
    "doc_id",
    "ordinal",
    "text",
    "char_start",
    "char_end",
    "page_start",
    "page_end",
    "word_count",
)


class RepositoryError(Exception):
    """Error base del repositorio de metadatos."""


class DuplicateDocumentError(RepositoryError):
    """Ya existe un documento con el mismo contenido en la colección."""

    def __init__(self, existing: Document) -> None:
        super().__init__(f"documento duplicado: {existing.doc_id}")
        self.existing = existing


class DocumentNotFoundError(RepositoryError, LookupError):
    """No existe el documento solicitado."""


class SchemaVersionError(RepositoryError):
    """La base existente usa una versión de esquema no soportada."""


def _document_to_row(document: Document) -> tuple[Any, ...]:
    data = document.model_dump(mode="json")
    data["extra"] = json.dumps(data["extra"], ensure_ascii=False, sort_keys=True)
    return tuple(data[column] for column in _DOCUMENT_COLUMNS)


def _row_to_document(row: sqlite3.Row) -> Document:
    data = dict(row)
    data["extra"] = json.loads(data["extra"])
    return Document.model_validate(data)


def _row_to_chunk(row: sqlite3.Row) -> Chunk:
    return Chunk.model_validate(dict(row))


class DocumentRepository:
    """CRUD de ``Document`` y ``Chunk`` sobre un archivo SQLite."""

    def __init__(self, db_path: str | os.PathLike[str]) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    # -- infraestructura ---------------------------------------------------
    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:  # commit / rollback automático
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise SchemaVersionError(
                    f"versión de esquema {version} no soportada (se esperaba {SCHEMA_VERSION})"
                )
            connection.executescript(_SCHEMA)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # -- documentos --------------------------------------------------------
    def add_document(self, document: Document) -> Document:
        """Inserta un documento; lanza ``DuplicateDocumentError`` si ya existe."""
        existing = self.find_by_hash(document.sha256, document.collection)
        if existing is not None:
            raise DuplicateDocumentError(existing)
        placeholders = ", ".join("?" for _ in _DOCUMENT_COLUMNS)
        try:
            with self._connect() as connection:
                connection.execute(
                    f"INSERT INTO documents ({', '.join(_DOCUMENT_COLUMNS)}) "
                    f"VALUES ({placeholders})",
                    _document_to_row(document),
                )
        except sqlite3.IntegrityError as exc:
            current = self.get_document_or_none(document.doc_id)
            if current is not None:
                raise DuplicateDocumentError(current) from exc
            raise RepositoryError(f"no se pudo guardar el documento: {exc}") from exc
        return document

    def get_document_or_none(self, doc_id: str) -> Optional[Document]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
            ).fetchone()
        return _row_to_document(row) if row else None

    def get_document(self, doc_id: str) -> Document:
        document = self.get_document_or_none(doc_id)
        if document is None:
            raise DocumentNotFoundError(f"documento no encontrado: {doc_id}")
        return document

    def find_by_hash(self, sha256: str, collection: str) -> Optional[Document]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE sha256 = ? AND collection = ?",
                (sha256, collection),
            ).fetchone()
        return _row_to_document(row) if row else None

    def list_documents(
        self, collection: str | None = None, *, limit: int = 100, offset: int = 0
    ) -> list[Document]:
        if limit < 1 or offset < 0:
            raise ValueError("limit debe ser >= 1 y offset >= 0")
        query = "SELECT * FROM documents"
        params: list[Any] = []
        if collection is not None:
            query += " WHERE collection = ?"
            params.append(collection)
        query += " ORDER BY created_at, doc_id LIMIT ? OFFSET ?"
        params.extend((limit, offset))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_row_to_document(row) for row in rows]

    def count_documents(self, collection: str | None = None) -> int:
        with self._connect() as connection:
            if collection is None:
                row = connection.execute("SELECT COUNT(*) FROM documents").fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) FROM documents WHERE collection = ?", (collection,)
                ).fetchone()
        return int(row[0])

    def update_extraction(
        self,
        doc_id: str,
        status: ExtractionStatus,
        *,
        error: str | None = None,
        page_count: int | None = None,
    ) -> Document:
        """Actualiza el estado de extracción validando con el modelo."""
        document = self.get_document(doc_id)
        updated = document.model_copy(
            update={
                "extraction_status": status,
                "extraction_error": error,
                "page_count": page_count if page_count is not None else document.page_count,
                "updated_at": utc_now(),
            }
        )
        updated = Document.model_validate(updated.model_dump())
        with self._connect() as connection:
            connection.execute(
                "UPDATE documents SET extraction_status = ?, extraction_error = ?, "
                "page_count = ?, updated_at = ? WHERE doc_id = ?",
                (
                    updated.extraction_status.value,
                    updated.extraction_error,
                    updated.page_count,
                    _isoformat(updated.updated_at),
                    doc_id,
                ),
            )
        return updated

    def update_extra(self, doc_id: str, updates: dict[str, Any]) -> Document:
        """Combina ``updates`` con los metadatos adicionales del documento."""
        document = self.get_document(doc_id)
        extra = {**document.extra, **updates}
        now = utc_now()
        Document.model_validate({**document.model_dump(), "extra": extra, "updated_at": now})
        with self._connect() as connection:
            connection.execute(
                "UPDATE documents SET extra = ?, updated_at = ? WHERE doc_id = ?",
                (json.dumps(extra, ensure_ascii=False, sort_keys=True), _isoformat(now), doc_id),
            )
        return self.get_document(doc_id)

    def collection_signature(self, collection: str | None) -> tuple[Any, ...]:
        """Firma barata que cambia al cargar, borrar o refragmentar documentos."""
        where, params = ("", ()) if collection is None else ("WHERE d.collection = ?", (collection,))
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(DISTINCT d.doc_id), COALESCE(MAX(d.updated_at), ''), "
                "COUNT(c.chunk_id), COALESCE(SUM(c.char_end), 0) "
                f"FROM documents d LEFT JOIN chunks c ON c.doc_id = d.doc_id {where}",
                params,
            ).fetchone()
        return tuple(row)

    def count_chunks(self, doc_id: str | None = None) -> int:
        with self._connect() as connection:
            if doc_id is None:
                row = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) FROM chunks WHERE doc_id = ?", (doc_id,)
                ).fetchone()
        return int(row[0])

    def delete_document(self, doc_id: str) -> None:
        """Elimina metadatos y fragmentos (el original se gestiona aparte)."""
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        if cursor.rowcount == 0:
            raise DocumentNotFoundError(f"documento no encontrado: {doc_id}")

    # -- fragmentos --------------------------------------------------------
    def replace_chunks(self, doc_id: str, chunks: Iterable[Chunk]) -> int:
        """Reemplaza atómicamente todos los fragmentos de un documento.

        Pensado para la reindexación: si algún fragmento es inválido, la
        transacción se revierte y se conservan los fragmentos anteriores.
        """
        chunk_list = list(chunks)
        ordinals = [chunk.ordinal for chunk in chunk_list]
        if len(set(ordinals)) != len(ordinals):
            raise ValueError("los fragmentos tienen ordinales repetidos")
        foreign = [chunk.chunk_id for chunk in chunk_list if chunk.doc_id != doc_id]
        if foreign:
            raise ValueError(f"fragmentos de otro documento: {foreign[:3]}")
        self.get_document(doc_id)
        placeholders = ", ".join("?" for _ in _CHUNK_COLUMNS)
        rows = [
            tuple(chunk.model_dump()[column] for column in _CHUNK_COLUMNS)
            for chunk in chunk_list
        ]
        with self._connect() as connection:
            connection.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            connection.executemany(
                f"INSERT INTO chunks ({', '.join(_CHUNK_COLUMNS)}) VALUES ({placeholders})",
                rows,
            )
            connection.execute(
                "UPDATE documents SET updated_at = ? WHERE doc_id = ?",
                (_isoformat(utc_now()), doc_id),
            )
        return len(rows)

    def get_chunks(self, doc_id: str) -> list[Chunk]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chunks WHERE doc_id = ? ORDER BY ordinal", (doc_id,)
            ).fetchall()
        return [_row_to_chunk(row) for row in rows]

    def get_chunk(self, chunk_id: str) -> Optional[Chunk]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
        return _row_to_chunk(row) if row else None

    def get_chunks_by_ids(self, chunk_ids: Sequence[str]) -> dict[str, Chunk]:
        """Fragmentos por ``chunk_id`` en una sola consulta (los inexistentes se omiten)."""
        found: dict[str, Chunk] = {}
        ids = list(dict.fromkeys(chunk_ids))
        with self._connect() as connection:
            for start in range(0, len(ids), 500):  # límite de parámetros de SQLite
                batch = ids[start : start + 500]
                rows = connection.execute(
                    f"SELECT * FROM chunks WHERE chunk_id IN ({','.join('?' * len(batch))})", batch
                ).fetchall()
                found.update((row["chunk_id"], _row_to_chunk(row)) for row in rows)
        return found

    def iter_chunks(self, collection: str | None = None) -> Iterator[Chunk]:
        """Recorre fragmentos en orden estable (útil para construir índices)."""
        query = "SELECT c.* FROM chunks c JOIN documents d ON d.doc_id = c.doc_id"
        params: tuple[Any, ...] = ()
        if collection is not None:
            query += " WHERE d.collection = ?"
            params = (collection,)
        query += " ORDER BY c.doc_id, c.ordinal"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        for row in rows:
            yield _row_to_chunk(row)


def _isoformat(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
