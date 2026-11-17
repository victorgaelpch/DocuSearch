"""Servicio de ingesta y consulta de documentos (DOC-04, DOC-07).

Orquesta, sin depender de HTTP: validación → extracción → fragmentación →
guardado del original → registro de metadatos y fragmentos. Si algo falla
después de guardar el original, se deshace todo para no dejar huérfanos.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.config import Settings

from backend.app.nlp.chunking import ChunkingConfig, chunk_extraction

from .models import DEFAULT_COLLECTION, Chunk, Document, ExtractionStatus, SourceType
from .readers import ExtractionResult, build_document, extract_document
from .repository import DocumentRepository, DuplicateDocumentError
from .storage import OriginalStore
from .validation import UploadValidationError, validate_upload


@dataclass(frozen=True)
class IngestResult:
    document: Document
    extraction: ExtractionResult
    chunks: list[Chunk]


@dataclass(frozen=True)
class RechunkReport:
    documents: int
    chunks: int
    failed: dict[str, str]


class DocumentService:
    """Casos de uso de documentos del usuario."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        paths = settings.paths.ensure()
        self.repository = DocumentRepository(paths.metadata_db)
        self.store = OriginalStore(paths.originals_dir)
        self.chunking = ChunkingConfig(settings.chunk_size, settings.chunk_overlap)

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
        return self._store_new(document, extraction, upload.data)

    def _store_new(
        self, document: Document, extraction: ExtractionResult, data: bytes
    ) -> IngestResult:
        """Guarda original, metadatos y fragmentos de forma todo-o-nada."""
        existing = self.repository.find_by_hash(document.sha256, document.collection)
        if existing is not None:
            raise DuplicateDocumentError(existing)
        document = document.model_copy(
            update={"extra": {**document.extra, "chunking": self.chunking.as_dict()}}
        )
        chunks = chunk_extraction(extraction, document.doc_id, self.chunking)

        created_file = not self.store.exists(document.storage_path)
        self.store.save(document.storage_path, data)
        added = False
        try:
            self.repository.add_document(document)
            added = True
            self.repository.replace_chunks(document.doc_id, chunks)
        except BaseException:
            if added:
                self.repository.delete_document(document.doc_id)
            if created_file:
                self.store.delete(document.storage_path)
            raise
        return IngestResult(document=document, extraction=extraction, chunks=chunks)

    def ingest_corpus_text(
        self,
        *,
        collection: str,
        title: str,
        text: str,
        filename: str,
        source_uri: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IngestResult:
        """Registra un texto de un corpus experimental (no de un usuario).

        Se guarda como ``.txt`` UTF-8 en ``originals/<colección>/`` y nunca se
        mezcla con la colección ``user``: el ``doc_id`` depende de la colección.
        """
        if collection == DEFAULT_COLLECTION:
            raise ValueError("los corpus experimentales no pueden usar la colección 'user'")
        data = text.encode("utf-8")
        extraction = extract_document(data, filename)
        if extraction.status is not ExtractionStatus.EXTRACTED:
            raise UploadValidationError("no_text", f"texto vacío o inválido: {title}")
        extraction = extraction.model_copy(update={"title": title[:500]})
        document = build_document(
            extraction, collection=collection, source_type=SourceType.CORPUS, source_uri=source_uri
        )
        if metadata:
            document = document.model_copy(update={"extra": {**document.extra, **metadata}})
        return self._store_new(document, extraction, data)

    def rechunk(self, collection: str | None = None) -> RechunkReport:
        """Vuelve a extraer y fragmentar desde los originales (reindexación).

        Usa la configuración de fragmentación actual. Un documento cuyo
        original falte o no pueda leerse se informa en ``failed`` sin
        interrumpir a los demás y conserva sus fragmentos anteriores.
        """
        processed = total_chunks = 0
        failed: dict[str, str] = {}
        offset = 0
        documents: list[Document] = []
        while batch := self.repository.list_documents(collection, limit=200, offset=offset):
            documents.extend(batch)
            offset += len(batch)
        for document in documents:
            try:
                data = self.store.read(document.storage_path)
            except (FileNotFoundError, OSError) as exc:
                failed[document.doc_id] = f"original no disponible: {exc}"
                continue
            extraction = extract_document(data, document.original_filename)
            if extraction.status is ExtractionStatus.FAILED:
                failed[document.doc_id] = extraction.error or "extracción fallida"
                continue
            chunks = chunk_extraction(extraction, document.doc_id, self.chunking)
            self.repository.replace_chunks(document.doc_id, chunks)
            self.repository.update_extra(document.doc_id, {"chunking": self.chunking.as_dict()})
            processed += 1
            total_chunks += len(chunks)
        return RechunkReport(documents=processed, chunks=total_chunks, failed=failed)

    def get_chunks(self, doc_id: str) -> list[Chunk]:
        self.repository.get_document(doc_id)
        return self.repository.get_chunks(doc_id)

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
