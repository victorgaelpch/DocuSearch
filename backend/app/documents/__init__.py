"""Modelos, persistencia de metadatos y almacenamiento de originales (DOC-02).

Los lectores PDF/DOCX/TXT corresponden a DOC-03.
"""

from .models import (
    DEFAULT_COLLECTION,
    WIKIPEDIA_COLLECTION,
    Chunk,
    Document,
    ExtractionStatus,
    SourceType,
    compute_sha256,
    make_chunk_id,
    make_document_id,
)
from .repository import (
    DocumentNotFoundError,
    DocumentRepository,
    DuplicateDocumentError,
    RepositoryError,
    SchemaVersionError,
)
from .storage import OriginalStore, UnsafePathError, build_storage_path

__all__ = [
    "DEFAULT_COLLECTION",
    "WIKIPEDIA_COLLECTION",
    "Chunk",
    "Document",
    "DocumentNotFoundError",
    "DocumentRepository",
    "DuplicateDocumentError",
    "ExtractionStatus",
    "OriginalStore",
    "RepositoryError",
    "SchemaVersionError",
    "SourceType",
    "UnsafePathError",
    "build_storage_path",
    "compute_sha256",
    "make_chunk_id",
    "make_document_id",
]
