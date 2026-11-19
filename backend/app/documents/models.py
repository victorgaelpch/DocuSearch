"""Contratos de datos ``Document`` y ``Chunk`` (DOC-02).

Decisiones principales (ver ``docs/modelo-datos.md``):

* Los identificadores son **deterministas**: ``doc_id`` se deriva de la
  colección y del SHA-256 del contenido original; ``chunk_id`` se deriva de
  ``doc_id`` y del orden del fragmento. Reprocesar el mismo archivo produce los
  mismos IDs, lo que permite reindexar sin cambiar el esquema de consulta.
* ``Document`` guarda solo metadatos y una **ruta relativa** al original;
  el texto extraído vive en ``Chunk`` y los índices en otro directorio.
* Las páginas se numeran desde 1 y son opcionales (DOCX/TXT no tienen
  paginación fiable).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHA256_PATTERN = r"^[0-9a-f]{64}$"
DOC_ID_PATTERN = r"^doc_[0-9a-f]{24}$"
CHUNK_ID_PATTERN = r"^doc_[0-9a-f]{24}_c\d{5}$"
COLLECTION_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"

DEFAULT_COLLECTION = "user"
"""Documentos personales cargados por usuarios."""

WIKIPEDIA_COLLECTION = "wikipedia_es"
"""Corpus experimental académico, separado de los documentos de usuario."""


class SourceType(str, Enum):
    """Procedencia del documento."""

    UPLOAD = "upload"
    CORPUS = "corpus"
    GOOGLE_DOCS = "google_docs"


class ExtractionStatus(str, Enum):
    """Estado del proceso de extracción de texto."""

    PENDING = "pending"
    EXTRACTED = "extracted"
    EMPTY = "empty"
    NEEDS_OCR = "needs_ocr"
    FAILED = "failed"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def compute_sha256(data: bytes) -> str:
    """SHA-256 hexadecimal del contenido binario original."""
    return hashlib.sha256(data).hexdigest()


def make_document_id(sha256: str, collection: str = DEFAULT_COLLECTION) -> str:
    """ID estable de documento a partir de colección + hash del contenido."""
    if not re.fullmatch(SHA256_PATTERN, sha256):
        raise ValueError("sha256 debe ser un hash hexadecimal de 64 caracteres en minúsculas")
    if not re.fullmatch(COLLECTION_PATTERN, collection):
        raise ValueError(f"colección inválida: {collection!r}")
    digest = hashlib.sha256(f"{collection}:{sha256}".encode("utf-8")).hexdigest()
    return f"doc_{digest[:24]}"


def make_chunk_id(doc_id: str, ordinal: int) -> str:
    """ID estable de fragmento: ``<doc_id>_c<orden de 5 dígitos>``."""
    if not re.fullmatch(DOC_ID_PATTERN, doc_id):
        raise ValueError(f"doc_id inválido: {doc_id!r}")
    if not 0 <= ordinal <= 99_999:
        raise ValueError("ordinal debe estar entre 0 y 99999")
    return f"{doc_id}_c{ordinal:05d}"


def _validate_relative_storage_path(value: str) -> str:
    """Acepta solo rutas relativas POSIX sin ``..`` ni unidades de Windows."""
    if not value or "\\" in value or ":" in value or "\x00" in value:
        raise ValueError("storage_path debe ser una ruta relativa POSIX segura")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("..", ".", "") for part in path.parts):
        raise ValueError("storage_path no puede ser absoluta ni contener '..'")
    return value


class Document(BaseModel):
    """Metadatos persistentes de un documento original."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    doc_id: str = Field(pattern=DOC_ID_PATTERN)
    collection: str = Field(default=DEFAULT_COLLECTION, pattern=COLLECTION_PATTERN)
    source_type: SourceType = SourceType.UPLOAD
    title: str = Field(min_length=1, max_length=500)
    original_filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=3, max_length=255)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=SHA256_PATTERN)
    storage_path: str = Field(
        description="Ruta del original relativa al directorio de originales.",
    )
    source_uri: Optional[str] = Field(
        default=None,
        max_length=2048,
        description="Procedencia externa (p. ej. URL de Wikipedia) si aplica.",
    )
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    extraction_status: ExtractionStatus = ExtractionStatus.PENDING
    extraction_error: Optional[str] = Field(default=None, max_length=2000)
    page_count: Optional[int] = Field(default=None, ge=0)
    language: str = Field(default="es", min_length=2, max_length=16)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("storage_path")
    @classmethod
    def _check_storage_path(cls, value: str) -> str:
        return _validate_relative_storage_path(value)

    @field_validator("original_filename")
    @classmethod
    def _check_filename(cls, value: str) -> str:
        if "/" in value or "\\" in value or "\x00" in value:
            raise ValueError("original_filename no puede contener separadores de ruta")
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> "Document":
        if self.doc_id != make_document_id(self.sha256, self.collection):
            raise ValueError("doc_id no corresponde a la colección y al sha256")
        if self.extraction_status is ExtractionStatus.FAILED and not self.extraction_error:
            raise ValueError("un documento con extracción fallida requiere extraction_error")
        return self

    @classmethod
    def new(
        cls,
        *,
        content: bytes,
        original_filename: str,
        mime_type: str,
        storage_path: str,
        title: str | None = None,
        collection: str = DEFAULT_COLLECTION,
        source_type: SourceType = SourceType.UPLOAD,
        source_uri: str | None = None,
    ) -> "Document":
        """Construye un documento calculando hash, tamaño e ID estable."""
        sha256 = compute_sha256(content)
        return cls(
            doc_id=make_document_id(sha256, collection),
            collection=collection,
            source_type=source_type,
            title=title or PurePosixPath(original_filename).stem or original_filename,
            original_filename=original_filename,
            mime_type=mime_type,
            size_bytes=len(content),
            sha256=sha256,
            storage_path=storage_path,
            source_uri=source_uri,
        )


class Chunk(BaseModel):
    """Fragmento de texto extraído, trazable a documento, página y offsets."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(pattern=CHUNK_ID_PATTERN)
    doc_id: str = Field(pattern=DOC_ID_PATTERN)
    ordinal: int = Field(ge=0, le=99_999, description="Orden del fragmento en el documento.")
    text: str = Field(min_length=1)
    char_start: int = Field(ge=0, description="Offset inicial en el texto extraído completo.")
    char_end: int = Field(gt=0, description="Offset final (exclusivo).")
    page_start: Optional[int] = Field(default=None, ge=1)
    page_end: Optional[int] = Field(default=None, ge=1)
    word_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_consistency(self) -> "Chunk":
        if self.chunk_id != make_chunk_id(self.doc_id, self.ordinal):
            raise ValueError("chunk_id no corresponde a doc_id y ordinal")
        if self.char_end <= self.char_start:
            raise ValueError("char_end debe ser mayor que char_start")
        if (self.page_start is None) != (self.page_end is None):
            raise ValueError("page_start y page_end deben definirse juntos")
        if self.page_start is not None and self.page_end is not None:
            if self.page_end < self.page_start:
                raise ValueError("page_end no puede ser menor que page_start")
        return self

    @classmethod
    def new(
        cls,
        *,
        doc_id: str,
        ordinal: int,
        text: str,
        char_start: int,
        char_end: int,
        page_start: int | None = None,
        page_end: int | None = None,
    ) -> "Chunk":
        """Construye un fragmento con ID estable y conteo de palabras."""
        return cls(
            chunk_id=make_chunk_id(doc_id, ordinal),
            doc_id=doc_id,
            ordinal=ordinal,
            text=text,
            char_start=char_start,
            char_end=char_end,
            page_start=page_start,
            page_end=page_start if page_end is None and page_start is not None else page_end,
            word_count=len(text.split()),
        )
