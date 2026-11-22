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
from .google_docs import fetch_public_doc
from .readers import ExtractionResult, build_document, extract_document
from .repository import DocumentNotFoundError, DocumentRepository, DuplicateDocumentError
from .storage import OriginalStore
from .validation import UploadValidationError, validate_upload


@dataclass(frozen=True)
class IngestResult:
    document: Document
    extraction: ExtractionResult
    chunks: list[Chunk]


@dataclass(frozen=True)
class DeleteResult:
    """Resultado de eliminar un documento (DOC-30)."""

    document: Document
    chunk_ids: list[str]
    original_removed: bool


EDITABLE_METADATA = ("description", "tags")
MAX_DESCRIPTION = 2000
MAX_TAGS = 20
MAX_TAG_CHARS = 40


@dataclass(frozen=True)
class RechunkReport:
    documents: int
    chunks: int
    failed: dict[str, str]


@dataclass(frozen=True)
class OcrReport:
    """Resultado de reprocesar con OCR los documentos ``needs_ocr`` (DOC-23)."""

    pending: int
    recognized: list[str]
    still_pending: list[str]
    failed: dict[str, str]


class DocumentService:
    """Casos de uso de documentos del usuario."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        paths = settings.paths.ensure()
        self.repository = DocumentRepository(paths.metadata_db)
        self.store = OriginalStore(paths.originals_dir)
        self.chunking = ChunkingConfig(settings.chunk_size, settings.chunk_overlap)
        # inyectable en pruebas: descarga de Google Docs públicos (DOC-22)
        self.fetch_google_doc = fetch_public_doc

    def ingest(
        self,
        filename: str | None,
        data: bytes,
        *,
        source_type: SourceType = SourceType.UPLOAD,
        source_uri: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> IngestResult:
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

        document = build_document(
            extraction, collection=DEFAULT_COLLECTION, source_type=source_type, source_uri=source_uri
        )
        if extra:
            document = document.model_copy(update={"extra": {**document.extra, **extra}})
        return self._store_new(document, extraction, upload.data)

    def ingest_google_doc(self, url: str) -> IngestResult:
        """Importa un Google Doc **público** por enlace (DOC-22).

        Lanza ``RemoteImportError`` (subclase de ``UploadValidationError``) si
        el enlace no es válido, el documento no es público o no se puede
        descargar.
        """
        remote = self.fetch_google_doc(url, max_bytes=self.settings.max_upload_bytes)
        return self.ingest(
            remote.filename,
            remote.data,
            source_type=SourceType.GOOGLE_DOCS,
            source_uri=remote.source_uri,
            extra={"google_doc_id": remote.doc_id},
        )

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

    def process_pending_ocr(self, collection: str | None = DEFAULT_COLLECTION) -> OcrReport:
        """Vuelve a extraer los documentos ``needs_ocr``; los que el OCR reconoce pasan a ``extracted``.

        Requiere Tesseract (ver ``documents/ocr.py``). Los que siguen sin texto
        se quedan como estaban.
        """
        pending: list[Document] = []
        offset = 0
        while batch := self.repository.list_documents(collection, limit=200, offset=offset):
            pending += [d for d in batch if d.extraction_status is ExtractionStatus.NEEDS_OCR]
            offset += len(batch)
        recognized: list[str] = []
        still: list[str] = []
        failed: dict[str, str] = {}
        for document in pending:
            try:
                data = self.store.read(document.storage_path)
            except (FileNotFoundError, OSError) as exc:
                failed[document.doc_id] = f"original no disponible: {exc}"
                continue
            extraction = extract_document(data, document.original_filename)
            if extraction.status is not ExtractionStatus.EXTRACTED:
                still.append(document.doc_id)
                continue
            chunks = chunk_extraction(extraction, document.doc_id, self.chunking)
            self.repository.replace_chunks(document.doc_id, chunks)
            self.repository.update_extraction(
                document.doc_id, ExtractionStatus.EXTRACTED, error=None, page_count=extraction.page_count
            )
            extra: dict[str, Any] = {**extraction.metadata, "chunking": self.chunking.as_dict()}
            extra["warnings"] = list(extraction.warnings)
            self.repository.update_extra(document.doc_id, extra)
            recognized.append(document.doc_id)
        return OcrReport(pending=len(pending), recognized=recognized, still_pending=still, failed=failed)

    def document_text(self, doc_id: str) -> tuple[str, list[Chunk]]:
        """Texto extraído reconstruido a partir de los fragmentos (DOC-28).

        Los fragmentos son subcadenas exactas del texto extraído
        (``text[char_start:char_end]``) y se solapan, así que su unión
        reproduce el texto sin volver a leer el original (ni repetir el OCR).
        Si hubiera huecos (traslape 0), se rellenan con espacios del mismo
        largo para que los offsets sigan siendo válidos.
        """
        chunks = self.get_chunks(doc_id)
        parts: list[str] = []
        cursor = 0
        for chunk in chunks:
            if chunk.char_start > cursor:
                parts.append(" " * (chunk.char_start - cursor))
                cursor = chunk.char_start
            if chunk.char_end > cursor:
                parts.append(chunk.text[cursor - chunk.char_start :])
                cursor = chunk.char_end
        return "".join(parts), chunks

    def get_user_document(self, doc_id: str) -> Document:
        """Documento de la colección ``user``; los corpus no se editan ni borran aquí."""
        document = self.repository.get_document(doc_id)
        if document.collection != DEFAULT_COLLECTION:
            raise DocumentNotFoundError(f"documento no encontrado: {doc_id}")
        return document

    def update_document(
        self,
        doc_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> Document:
        """Edita título, descripción y etiquetas sin modificar el original (DOC-30).

        Solo se aceptan esas claves: los metadatos del sistema (fragmentación,
        OCR, avisos) no se pueden sobrescribir.
        """
        self.get_user_document(doc_id)
        if title is not None:
            clean = " ".join(title.split())
            if not clean or len(clean) > 500:
                raise UploadValidationError("invalid_title", "el título debe tener entre 1 y 500 caracteres")
            self.repository.update_title(doc_id, clean)
        updates: dict[str, Any] = {}
        if description is not None:
            text = description.strip()
            if len(text) > MAX_DESCRIPTION:
                raise UploadValidationError("invalid_metadata", f"la descripción admite hasta {MAX_DESCRIPTION} caracteres")
            updates["description"] = text
        if tags is not None:
            clean_tags = list(dict.fromkeys(" ".join(t.split()) for t in tags if t and t.strip()))
            if len(clean_tags) > MAX_TAGS or any(len(t) > MAX_TAG_CHARS for t in clean_tags):
                raise UploadValidationError(
                    "invalid_metadata", f"hasta {MAX_TAGS} etiquetas de {MAX_TAG_CHARS} caracteres como máximo"
                )
            updates["tags"] = clean_tags
        if updates:
            self.repository.update_extra(doc_id, updates)
        return self.repository.get_document(doc_id)

    def delete_document(self, doc_id: str) -> DeleteResult:
        """Elimina original, metadatos y fragmentos de forma compensada (DOC-30).

        1. El original se aparta (renombrado) para poder restaurarlo.
        2. Se borran metadatos y fragmentos en una transacción SQLite.
        3. Si el paso 2 falla, el original vuelve a su sitio y nada cambia.
        4. Si el paso 2 se confirma, se borra el original apartado.
        """
        document = self.get_user_document(doc_id)
        chunk_ids = [chunk.chunk_id for chunk in self.repository.get_chunks(doc_id)]
        staged = self.store.stage_delete(document.storage_path)
        try:
            self.repository.delete_document(doc_id)
        except BaseException:
            self.store.restore(staged, document.storage_path)
            raise
        return DeleteResult(document=document, chunk_ids=chunk_ids, original_removed=self.store.discard(staged))

    def get_chunks(self, doc_id: str) -> list[Chunk]:
        self.repository.get_document(doc_id)
        return self.repository.get_chunks(doc_id)

    def list_documents(
        self,
        *,
        limit: int,
        offset: int,
        text: str | None = None,
        mime_types: list[str] | None = None,
        statuses: list[str] | None = None,
        newest_first: bool = False,
    ) -> tuple[list[Document], int]:
        """Documentos de la colección ``user`` con filtros opcionales (DOC-27)."""
        return self.repository.filter_documents(
            DEFAULT_COLLECTION,
            text=(text or "").strip() or None,
            mime_types=mime_types,
            statuses=statuses,
            limit=limit,
            offset=offset,
            newest_first=newest_first,
        )

    def get_document(self, doc_id: str) -> Document:
        return self.repository.get_document(doc_id)

    def original_path(self, document: Document) -> Path:
        """Ruta absoluta del original; ``FileNotFoundError`` si falta en disco."""
        path = self.store.resolve(document.storage_path)
        if not path.is_file():
            raise FileNotFoundError(document.storage_path)
        return path
