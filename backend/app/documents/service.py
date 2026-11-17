"""Servicio de ingesta y consulta de documentos (DOC-04).

Orquesta, sin depender de HTTP: validación → extracción → guardado del
original → registro de metadatos. Si algo falla después de guardar el
original, este se elimina para no dejar archivos huérfanos.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.app.config import Settings

from .models import DEFAULT_COLLECTION, Document, ExtractionStatus
from .readers import ExtractionResult, build_document, extract_document
from .repository import DocumentRepository, DuplicateDocumentError
from .storage import OriginalStore
from .validation import UploadValidationError, validate_upload


@dataclass(frozen=True)
class IngestResult:
    document: Document
    extraction: ExtractionResult


class DocumentService:
    """Casos de uso de documentos del usuario."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        paths = settings.paths.ensure()
        self.repository = DocumentRepository(paths.metadata_db)
        self.store = OriginalStore(paths.originals_dir)

    def ingest(self, filename: str | None, data: bytes) -> IngestResult:
        """Valida, extrae y guarda un archivo de la colección ``user``.

        Lanza ``UploadValidationError`` si el archivo se rechaza y
        ``DuplicateDocumentError`` si ya existe el mismo contenido.
        Los PDF sin capa de texto se aceptan con estado ``needs_ocr``.
        """
        upload = validate_upload(
            filename,
            data,
            max_bytes=self.settings.max_upload_bytes,
            max_docx_uncompressed_bytes=self.settings.max_docx_uncompressed_bytes,
        )
        extraction = extract_document(upload.data, upload.filename)
        if extraction.status is ExtractionStatus.FAILED:
            raise UploadValidationError(
                "corrupt_file", f"no se pudo leer el archivo: {extraction.error}"
            )
        if extraction.status is ExtractionStatus.EMPTY:
            raise UploadValidationError(
                "no_text", "el archivo no contiene texto extraíble"
            )

        document = build_document(extraction, collection=DEFAULT_COLLECTION)
        existing = self.repository.find_by_hash(document.sha256, document.collection)
        if existing is not None:
            raise DuplicateDocumentError(existing)

        created_file = not self.store.exists(document.storage_path)
        self.store.save(document.storage_path, upload.data)
        try:
            self.repository.add_document(document)
        except BaseException:
            if created_file:
                self.store.delete(document.storage_path)
            raise
        return IngestResult(document=document, extraction=extraction)

    def list_documents(self, *, limit: int, offset: int) -> tuple[list[Document], int]:
        items = self.repository.list_documents(DEFAULT_COLLECTION, limit=limit, offset=offset)
        return items, self.repository.count_documents(DEFAULT_COLLECTION)

    def get_document(self, doc_id: str) -> Document:
        return self.repository.get_document(doc_id)

    def original_path(self, document: Document) -> Path:
        """Ruta absoluta del original; ``FileNotFoundError`` si falta en disco."""
        path = self.store.resolve(document.storage_path)
        if not path.is_file():
            raise FileNotFoundError(document.storage_path)
        return path
