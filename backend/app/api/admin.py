"""Panel de índices y tareas de reindexación (DOC-31). Solo Administrador."""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, Path, Request, status
from pydantic import BaseModel

from backend.app.api.documents import ErrorResponse, _error, get_document_service
from backend.app.api.search import get_search_engine
from backend.app.auth.dependencies import require_admin, require_admin_mutation
from backend.app.documents.models import DEFAULT_COLLECTION
from backend.app.documents.service import DocumentService
from backend.app.jobs import JobConflictError, JobContext, JobKind, JobManager
from backend.app.nlp import embeddings
from backend.app.search.engine import SearchEngine
from backend.app.search.semantic_index import META_FILE

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

CollectionPath = Path(pattern=r"^[a-z0-9_]{1,64}$", description="Colección (user, wikipedia_es, …)")


def get_job_manager(request: Request) -> JobManager:
    manager = getattr(request.app.state, "jobs", None)
    if manager is None:
        manager = JobManager()
        request.app.state.jobs = manager
    return manager


def _semantic_on_disk(service: DocumentService, collection: str, current: set[str]) -> dict[str, Any]:
    """Estado del índice FAISS leyendo solo ``meta.json`` (no carga el modelo)."""
    meta_path = service.settings.paths.indexes_dir / "semantic" / collection / META_FILE
    if not meta_path.is_file():
        return {"built": False}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"built": False, "error": "meta.json ilegible: reconstruya el índice"}
    indexed = {entry.get("chunk_id") for entry in meta.get("entries", [])}
    encoder = meta.get("encoder", {})
    return {
        "built": True,
        "chunks": len(indexed),
        "version": meta.get("version"),
        "updated_at": meta.get("updated_at"),
        "model": encoder.get("model") or encoder.get("encoder"),
        "dimension": encoder.get("dimension"),
        "pending_chunks": len(current - indexed),
        "stale_entries": len(indexed - current),
        "in_sync": indexed == current,
    }


@router.get("/indexes", summary="Estado de colecciones, índices y tareas activas")
def indexes(
    request: Request,
    service: DocumentService = Depends(get_document_service),
    engine: SearchEngine = Depends(get_search_engine),
    jobs: JobManager = Depends(get_job_manager),
) -> dict[str, Any]:
    stats = service.repository.collection_stats()
    names = sorted(set(stats) | {DEFAULT_COLLECTION}, key=lambda c: (c != DEFAULT_COLLECTION, c))
    semantic_ready = request.app.state.encoder_factory is not None or embeddings.semantic_available()
    collections = []
    for name in names:
        counts = stats.get(name, {"documents": 0, "chunks": 0, "needs_ocr": 0})
        info: dict[str, Any] = {"collection": name, **counts, "active_job": jobs.active(name)}
        if info["active_job"] is None:
            # versión léxica real (construye el índice si hacía falta)
            description = engine.describe(name)
            info["lexical"] = {
                "version": description["index_version"],
                "chunks": description["chunks"],
                "methods": [i["method"] for i in description["indexes"] if i["method"] in ("bm25", "tfidf")],
            }
        else:
            info["lexical"] = None  # no se toca mientras se reconstruye
        info["semantic"] = _semantic_on_disk(service, name, service.repository.chunk_id_set(name))
        collections.append(info)
    return {
        "collections": collections,
        "semantic_available": semantic_ready,
        "embedding_model": {"name": embeddings.MODEL_NAME, "revision": embeddings.MODEL_REVISION},
        "concurrent_jobs": 1,
        "recent_jobs": jobs.recent(10),
    }


class JobIn(BaseModel):
    kind: JobKind


def _job_function(kind: JobKind, collection: str, service: DocumentService, engine: SearchEngine):
    def reindex(ctx: JobContext) -> dict[str, Any]:
        ctx.step("Refragmentando desde los originales")
        report = service.rechunk(collection, progress=ctx.progress)
        ctx.step("Reconstruyendo BM25 y TF-IDF")
        rebuilt = engine.rebuild(collection)
        return {
            "documents": report.documents,
            "chunks": report.chunks,
            "failed": report.failed,
            "index_version": rebuilt["index_version"],
            "chunking": service.chunking.as_dict(),
        }

    def semantic(ctx: JobContext) -> dict[str, Any]:
        ctx.step("Codificando fragmentos nuevos o modificados (FAISS)")
        return {**engine.sync_semantic(collection), "failed": {}}

    def semantic_rebuild(ctx: JobContext) -> dict[str, Any]:
        ctx.step("Codificando todos los fragmentos (FAISS desde cero)")
        return {**engine.rebuild_semantic(collection), "failed": {}}

    def ocr(ctx: JobContext) -> dict[str, Any]:
        ctx.step("Reconociendo texto en PDF escaneados")
        report = service.process_pending_ocr(collection)
        return {
            "pending": report.pending,
            "recognized": report.recognized,
            "still_pending": report.still_pending,
            "failed": report.failed,
        }

    return {JobKind.REINDEX: reindex, JobKind.SEMANTIC: semantic, JobKind.SEMANTIC_REBUILD: semantic_rebuild, JobKind.OCR: ocr}[kind]


@router.post(
    "/indexes/{collection}/jobs",
    status_code=status.HTTP_202_ACCEPTED,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="Iniciar una tarea de indexación (respuesta inmediata con su estado)",
    dependencies=[Depends(require_admin_mutation)],
)
def start_job(
    body: JobIn,
    collection: str = CollectionPath,
    service: DocumentService = Depends(get_document_service),
    engine: SearchEngine = Depends(get_search_engine),
    jobs: JobManager = Depends(get_job_manager),
):
    known = set(service.repository.collection_stats()) | {DEFAULT_COLLECTION}
    if collection not in known:
        return _error(404, "unknown_collection", "la colección no existe")
    try:
        job = jobs.submit(body.kind, collection, _job_function(body.kind, collection, service, engine))
    except JobConflictError as exc:
        return _error(409, "job_running", f"ya hay una tarea en curso en {collection}; espere a que termine")
    return jobs.snapshot(job.job_id)


@router.get("/jobs", summary="Últimas tareas")
def list_jobs(jobs: JobManager = Depends(get_job_manager)) -> dict[str, Any]:
    return {"items": jobs.recent(50)}


@router.get("/jobs/{job_id}", responses={404: {"model": ErrorResponse}}, summary="Estado real de una tarea")
def get_job(job_id: str = Path(pattern=r"^[0-9a-f]{32}$"), jobs: JobManager = Depends(get_job_manager)):
    snapshot: Optional[dict[str, Any]] = jobs.snapshot(job_id)
    if snapshot is None:
        return _error(404, "job_not_found", "la tarea no existe (las tareas se olvidan al reiniciar el servidor)")
    return snapshot
