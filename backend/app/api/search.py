"""Endpoint de búsqueda (DOC-10, DOC-14).

``GET /search?q=...&method=bm25&k=10&collection=user``

Recupera fragmentos de documentos PDF, DOCX y TXT cargados (colección
``user``) o del corpus experimental (``wikipedia_es``) con BM25 (por
defecto), TF-IDF o búsqueda semántica (``semantic``, requiere el extra
``semantic``). El orden es determinista para la misma ``index_version``.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from backend.app.api.documents import ErrorResponse, _error, get_document_service
from backend.app.documents.models import DEFAULT_COLLECTION, WIKIPEDIA_COLLECTION
from backend.app.documents.service import DocumentService
from backend.app.nlp.embeddings import EmbeddingUnavailableError
from backend.app.search.engine import SearchEngine
from backend.app.search.ranking import DEFAULT_TOP_K, MAX_TOP_K

router = APIRouter(tags=["search"])

MAX_QUERY_CHARS = 500


class Method(str, Enum):
    bm25 = "bm25"
    tfidf = "tfidf"
    semantic = "semantic"


class Collection(str, Enum):
    user = DEFAULT_COLLECTION
    wikipedia_es = WIKIPEDIA_COLLECTION


class SearchResultOut(BaseModel):
    rank: int
    score: float
    method: str
    doc_id: str
    chunk_id: str
    title: str
    original_filename: str
    snippet: str
    page: Optional[int] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    download_url: str


class SearchOut(BaseModel):
    query: str
    query_tokens: list[str]
    method: str
    k: int
    collection: str
    index_version: str
    total: int
    took_ms: float
    results: list[SearchResultOut]


def get_search_engine(
    request: Request, service: DocumentService = Depends(get_document_service)
) -> SearchEngine:
    """Motor único por aplicación; reconstruye índices solo si cambian los datos."""
    engine = getattr(request.app.state, "search_engine", None)
    if engine is None:
        engine = SearchEngine(
            service.repository,
            cache_path=service.settings.paths.indexes_dir / "lexical_tokens.json",
            encoder_factory=getattr(request.app.state, "encoder_factory", None),
        )
        request.app.state.search_engine = engine
    return engine


@router.get(
    "/search",
    response_model=SearchOut,
    responses={
        422: {"model": ErrorResponse, "description": "Consulta vacía o parámetros inválidos"},
        503: {"model": ErrorResponse, "description": "Búsqueda semántica no disponible (falta el extra `semantic` o el modelo)"},
    },
    summary="Buscar fragmentos por texto libre (BM25, TF-IDF o semántica)",
)
def search(
    q: Annotated[
        str,
        Query(
            min_length=1,
            max_length=MAX_QUERY_CHARS,
            description="Consulta en español",
            examples=["enfermedad transmitida por mosquitos"],
        ),
    ],
    method: Annotated[
        Method, Query(description="`bm25` (por defecto), `tfidf` o `semantic` (por significado)")
    ] = Method.bm25,
    k: Annotated[int, Query(ge=1, le=MAX_TOP_K, description="Número de resultados")] = DEFAULT_TOP_K,
    collection: Annotated[
        Collection, Query(description="`user` (documentos cargados) o `wikipedia_es` (corpus)")
    ] = Collection.user,
    engine: SearchEngine = Depends(get_search_engine),
):
    if not q.strip():
        return _error(422, "empty_query", "la consulta no puede estar vacía")
    if "�" in q:
        return _error(
            422, "invalid_encoding", "la consulta contiene caracteres inválidos; envíela en UTF-8"
        )
    try:
        response = engine.search(q, method=method.value, k=k, collection=collection.value)
    except EmbeddingUnavailableError as exc:
        return _error(503, "semantic_unavailable", str(exc))
    return SearchOut(
        query=response.query,
        query_tokens=response.query_tokens,
        method=response.method.value,
        k=response.k,
        collection=response.collection,
        index_version=response.index_version,
        total=len(response.hits),
        took_ms=response.took_ms,
        results=[
            SearchResultOut(
                **hit.model_dump(mode="json"), download_url=f"/documents/{hit.doc_id}/download"
            )
            for hit in response.hits
        ],
    )


@router.get(
    "/search/index",
    summary="Versión y parámetros de los índices de una colección",
)
def index_info(
    collection: Annotated[Collection, Query()] = Collection.user,
    engine: SearchEngine = Depends(get_search_engine),
) -> dict[str, Any]:
    return engine.describe(collection.value)

