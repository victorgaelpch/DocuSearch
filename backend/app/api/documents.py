"""Endpoints de documentos (DOC-04).

* ``POST /documents``: carga multipart de un PDF, DOCX o TXT.
* ``GET /documents``: lista paginada de documentos del usuario.
* ``GET /documents/{doc_id}``: metadatos de un documento.
* ``GET /documents/{doc_id}/download``: descarga del original como adjunto.
* ``GET /documents/{doc_id}/chunks``: fragmentos con offsets y páginas (DOC-07).

La ruta interna del original nunca se expone en las respuestas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, File, Path, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from backend.app.documents.models import DOC_ID_PATTERN, Document, ExtractionStatus
from backend.app.documents.repository import DocumentNotFoundError, DuplicateDocumentError
from backend.app.documents.service import DocumentService
from backend.app.documents.validation import UploadValidationError

router = APIRouter(prefix="/documents", tags=["documents"])

_READ_CHUNK = 1024 * 1024


class ErrorBody(BaseModel):
    code: str
    message: str
    doc_id: Optional[str] = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class DocumentOut(BaseModel):
    doc_id: str
    title: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    created_at: datetime
    updated_at: datetime
    extraction_status: ExtractionStatus
    extraction_error: Optional[str] = None
    page_count: Optional[int] = None
    language: str
    metadata: dict[str, Any]
    download_url: str
    source_type: str = "upload"
    source_uri: Optional[str] = None

    @classmethod
    def from_document(cls, document: Document) -> "DocumentOut":
        return cls(
            doc_id=document.doc_id,
            title=document.title,
            original_filename=document.original_filename,
            mime_type=document.mime_type,
            size_bytes=document.size_bytes,
            sha256=document.sha256,
            created_at=document.created_at,
            updated_at=document.updated_at,
            extraction_status=document.extraction_status,
            extraction_error=document.extraction_error,
            page_count=document.page_count,
            language=document.language,
            source_type=document.source_type.value,
            source_uri=document.source_uri,
            metadata=document.extra,
            download_url=f"/documents/{document.doc_id}/download",
        )


class UploadOut(DocumentOut):
    word_count: int
    chunk_count: int
    warnings: list[str]


class ChunkOut(BaseModel):
    chunk_id: str
    ordinal: int
    text: str
    char_start: int
    char_end: int
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    word_count: int


class ChunkListOut(BaseModel):
    doc_id: str
    chunking: dict[str, Any]
    items: list[ChunkOut]


class DocumentListOut(BaseModel):
    items: list[DocumentOut]
    total: int
    limit: int
    offset: int


def _error(status_code: int, code: str, message: str, doc_id: str | None = None) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, doc_id=doc_id))
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


def get_document_service(request: Request) -> DocumentService:
    """Servicio único por aplicación, creado en la primera petición."""
    service = getattr(request.app.state, "document_service", None)
    if service is None:
        service = DocumentService(request.app.state.settings)
        request.app.state.document_service = service
    return service


_ERRORS = {
    400: {"model": ErrorResponse, "description": "Archivo vacío o petición inválida"},
    409: {"model": ErrorResponse, "description": "Documento duplicado"},
    413: {"model": ErrorResponse, "description": "Archivo demasiado grande"},
    415: {"model": ErrorResponse, "description": "Formato o contenido no admitido"},
    422: {"model": ErrorResponse, "description": "Archivo dañado o sin texto"},
}

DocIdPath = Annotated[
    str, Path(pattern=DOC_ID_PATTERN, description="Identificador estable del documento")
]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=UploadOut,
    responses=_ERRORS,
    summary="Cargar un documento PDF, DOCX o TXT",
)
async def upload_document(
    request: Request,
    file: UploadFile = File(..., description="Archivo .pdf, .docx o .txt"),
    service: DocumentService = Depends(get_document_service),
):
    max_bytes = service.settings.max_upload_bytes
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > max_bytes + 64 * 1024:
        return _error(413, "file_too_large", f"el archivo supera el máximo de {max_bytes // (1024 * 1024)} MB")

    chunks: list[bytes] = []
    received = 0
    while chunk := await file.read(_READ_CHUNK):
        received += len(chunk)
        if received > max_bytes:
            return _error(413, "file_too_large", f"el archivo supera el máximo de {max_bytes // (1024 * 1024)} MB")
        chunks.append(chunk)
    await file.close()

    try:
        result = await run_in_threadpool(service.ingest, file.filename, b"".join(chunks))
    except UploadValidationError as exc:
        return _error(exc.status_code, exc.code, exc.message)
    except DuplicateDocumentError as exc:
        return _error(
            409, "duplicate_document", "el documento ya fue cargado", exc.existing.doc_id
        )

    base = DocumentOut.from_document(result.document).model_dump()
    return UploadOut(
        **base,
        word_count=result.extraction.word_count,
        chunk_count=len(result.chunks),
        warnings=result.extraction.warnings,
    )


class GoogleDocImportIn(BaseModel):
    url: str


@router.post(
    "/import",
    status_code=status.HTTP_201_CREATED,
    response_model=UploadOut,
    responses={
        **_ERRORS,
        403: {"model": ErrorResponse, "description": "El Google Doc no es público"},
        404: {"model": ErrorResponse, "description": "Google Docs no encontró el documento"},
        502: {"model": ErrorResponse, "description": "Error al contactar con Google Docs"},
        504: {"model": ErrorResponse, "description": "Google Docs no respondió a tiempo"},
    },
    summary="Importar un Google Doc público por enlace (DOC-22)",
)
async def import_google_doc(
    body: GoogleDocImportIn,
    service: DocumentService = Depends(get_document_service),
):
    """Descarga como DOCX un Google Doc compartido como "cualquier persona con el enlace"."""
    try:
        result = await run_in_threadpool(service.ingest_google_doc, body.url)
    except UploadValidationError as exc:
        return _error(exc.status_code, exc.code, exc.message)
    except DuplicateDocumentError as exc:
        return _error(409, "duplicate_document", "el documento ya fue cargado", exc.existing.doc_id)
    base = DocumentOut.from_document(result.document).model_dump()
    return UploadOut(
        **base,
        word_count=result.extraction.word_count,
        chunk_count=len(result.chunks),
        warnings=result.extraction.warnings,
    )


@router.get("", response_model=DocumentListOut, summary="Listar documentos cargados")
def list_documents(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: DocumentService = Depends(get_document_service),
) -> DocumentListOut:
    items, total = service.list_documents(limit=limit, offset=offset)
    return DocumentListOut(
        items=[DocumentOut.from_document(d) for d in items], total=total, limit=limit, offset=offset
    )


@router.get(
    "/{doc_id}",
    response_model=DocumentOut,
    responses={404: {"model": ErrorResponse}},
    summary="Consultar metadatos de un documento",
)
def get_document(
    doc_id: DocIdPath,
    service: DocumentService = Depends(get_document_service),
):
    try:
        return DocumentOut.from_document(service.get_document(doc_id))
    except DocumentNotFoundError:
        return _error(404, "not_found", "documento no encontrado")


@router.get(
    "/{doc_id}/download",
    response_class=FileResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Descargar el archivo original",
)
def download_document(
    doc_id: DocIdPath,
    service: DocumentService = Depends(get_document_service),
):
    try:
        document = service.get_document(doc_id)
        path = service.original_path(document)
    except DocumentNotFoundError:
        return _error(404, "not_found", "documento no encontrado")
    except FileNotFoundError:
        return _error(404, "original_missing", "el archivo original no está disponible")
    return FileResponse(
        path,
        media_type=document.mime_type,
        filename=document.original_filename,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )


@router.get(
    "/{doc_id}/chunks",
    response_model=ChunkListOut,
    responses={404: {"model": ErrorResponse}},
    summary="Listar los fragmentos de un documento",
)
def list_chunks(
    doc_id: DocIdPath,
    service: DocumentService = Depends(get_document_service),
):
    try:
        document = service.get_document(doc_id)
        chunks = service.get_chunks(doc_id)
    except DocumentNotFoundError:
        return _error(404, "not_found", "documento no encontrado")
    return ChunkListOut(
        doc_id=doc_id,
        chunking=document.extra.get("chunking", {}),
        items=[ChunkOut(**c.model_dump(exclude={"doc_id"})) for c in chunks],
    )
