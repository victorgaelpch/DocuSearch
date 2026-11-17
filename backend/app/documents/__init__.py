"""Modelos y persistencia (DOC-02) y lectores PDF/DOCX/TXT (DOC-03)."""

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
from .readers import (
    SUPPORTED_EXTENSIONS,
    CorruptFileError,
    EmptyFileError,
    ExtractionError,
    ExtractionResult,
    TextSection,
    UnsupportedFormatError,
    build_document,
    extract_document,
    get_reader,
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
    "SUPPORTED_EXTENSIONS",
    "CorruptFileError",
    "EmptyFileError",
    "ExtractionError",
    "ExtractionResult",
    "TextSection",
    "UnsupportedFormatError",
    "build_document",
    "extract_document",
    "get_reader",
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
