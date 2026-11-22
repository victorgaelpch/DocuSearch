"""Motor de búsqueda sobre los fragmentos persistidos (DOC-08/09/14).

Métodos: BM25 y TF-IDF (léxicos), ``semantic`` (embeddings + FAISS, DOC-14) e
``hybrid`` (BM25 + semántica con Reciprocal Rank Fusion, DOC-15).
La búsqueda semántica es opcional: requiere el extra ``semantic`` y, si falta,
lanza ``EmbeddingUnavailableError`` sin afectar a los métodos léxicos.

* Construye los índices de forma perezosa por colección y método.
* Detecta cambios en el repositorio (cargas, borrados, reindexación) mediante
  una firma barata en SQLite y reconstruye solo cuando cambia.
* Devuelve ``SearchHit`` (contrato de DOC-02) con documento, fragmento,
  página, puntuación y posición.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

from backend.app.documents.models import DEFAULT_COLLECTION, Chunk, Document
from backend.app.documents.repository import DocumentRepository
from backend.app.nlp import embeddings
from backend.app.nlp.embeddings import Encoder
from backend.app.nlp.lexical import LexicalPipeline, get_lexical_pipeline
from backend.app.nlp.semantic import prepare_semantic

from .lexical_corpus import LexicalCorpus, build_lexical_corpus
from .models import SearchHit, SearchMethod
from .ranking import DEFAULT_TOP_K, validate_k
from .bm25 import BM25Index
from .tfidf import TfidfIndex
from .hybrid import CANDIDATE_DEPTH, RRF_K, reciprocal_rank_fusion
from .semantic_index import SemanticIndexManager

SNIPPET_CHARS = 300


class LexicalIndex(Protocol):
    method: str

    def search(self, query_tokens: Any, k: int) -> list[tuple[int, float]]: ...

    def describe(self) -> dict[str, Any]: ...


IndexFactory = Callable[[LexicalCorpus], LexicalIndex]


def _tfidf_factory(corpus: LexicalCorpus) -> LexicalIndex:
    return TfidfIndex(corpus.tokens, corpus.chunk_ids)


def _bm25_factory(corpus: LexicalCorpus) -> LexicalIndex:
    return BM25Index(corpus.tokens, corpus.chunk_ids)


INDEX_FACTORIES: dict[SearchMethod, IndexFactory] = {
    SearchMethod.BM25: _bm25_factory,
    SearchMethod.TFIDF: _tfidf_factory,
}


class UnsupportedMethodError(ValueError):
    """Método de búsqueda no disponible."""


@dataclass
class SearchResponse:
    query: str
    method: SearchMethod
    k: int
    collection: str
    index_version: str
    query_tokens: list[str]
    hits: list[SearchHit]
    took_ms: float


@dataclass
class _CollectionState:
    signature: tuple[Any, ...]
    corpus: LexicalCorpus
    indexes: dict[SearchMethod, LexicalIndex] = field(default_factory=dict)


def make_snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    """Fragmento legible: limpieza semántica, una línea y corte por palabra."""
    clean = " ".join(prepare_semantic(text).split())
    if len(clean) <= limit:
        return clean
    cut = clean[:limit].rsplit(" ", 1)[0]
    return cut + "…"


class SearchEngine:
    """Búsqueda TF-IDF/BM25 sobre una o varias colecciones."""

    def __init__(
        self,
        repository: DocumentRepository,
        *,
        pipeline: Optional[LexicalPipeline] = None,
        cache_path: Path | None = None,
        indexes_dir: Path | None = None,
        encoder_factory: Callable[[], Encoder] | None = None,
    ) -> None:
        self.repository = repository
        self._pipeline = pipeline
        self.cache_path = cache_path
        self.indexes_dir = indexes_dir if indexes_dir is not None else (cache_path.parent if cache_path else None)
        self._encoder_factory = encoder_factory or embeddings.get_encoder
        self._semantic: SemanticIndexManager | None = None
        self._states: dict[str, _CollectionState] = {}
        self._lock = threading.RLock()

    @property
    def pipeline(self) -> LexicalPipeline:
        if self._pipeline is None:
            self._pipeline = get_lexical_pipeline()
        return self._pipeline

    @staticmethod
    def available_methods() -> list[str]:
        return [m.value for m in INDEX_FACTORIES] + [SearchMethod.SEMANTIC.value, SearchMethod.HYBRID.value]

    @property
    def semantic(self) -> SemanticIndexManager:
        """Gestor de índices FAISS, creado al primer uso (puede lanzar ``EmbeddingUnavailableError``)."""
        with self._lock:
            if self._semantic is None:
                self._semantic = SemanticIndexManager(self.repository, self._encoder_factory(), self.indexes_dir)
            return self._semantic

    def rebuild_semantic(self, collection: str = DEFAULT_COLLECTION) -> dict[str, Any]:
        return self.semantic.rebuild(collection).as_dict()

    def _semantic_description(self, collection: str) -> dict[str, Any]:
        """Estado del índice semántico sin forzar su construcción (puede tardar minutos)."""
        if self._semantic is None or collection not in self._semantic.last_reports:
            return {"method": "semantic", "available": embeddings.semantic_available(), "loaded": False}
        index = self._semantic.index(collection)
        return {**index.describe(), "available": True, "loaded": True}

    def _state(self, collection: str) -> _CollectionState:
        signature = self.repository.collection_signature(collection)
        with self._lock:
            state = self._states.get(collection)
            if state is None or state.signature != signature:
                corpus = build_lexical_corpus(
                    self.repository, self.pipeline, collection, self.cache_path
                )
                state = _CollectionState(signature=signature, corpus=corpus)
                self._states[collection] = state
            return state

    def _index(self, state: _CollectionState, method: SearchMethod) -> LexicalIndex:
        with self._lock:
            index = state.indexes.get(method)
            if index is None:
                index = INDEX_FACTORIES[method](state.corpus)
                state.indexes[method] = index
            return index

    def forget(self, collection: str) -> None:
        """Descarta el estado en memoria de ``collection`` (tras borrar documentos, DOC-30).

        Los índices léxicos se reconstruyen en la próxima búsqueda y el índice
        semántico se recarga del disco (ya purgado) en su próximo uso.
        """
        with self._lock:
            self._states.pop(collection, None)
            if self._semantic is not None:
                self._semantic.forget(collection)

    def rebuild(self, collection: str = DEFAULT_COLLECTION) -> dict[str, Any]:
        """Fuerza la reconstrucción de todos los índices de una colección."""
        with self._lock:
            self._states.pop(collection, None)
            state = self._state(collection)
            return {
                "collection": collection,
                "index_version": state.corpus.version,
                "indexes": [self._index(state, m).describe() for m in INDEX_FACTORIES],
            }

    def describe(self, collection: str = DEFAULT_COLLECTION) -> dict[str, Any]:
        state = self._state(collection)
        return {
            "collection": collection,
            "index_version": state.corpus.version,
            "chunks": len(state.corpus),
            "lexical_pipeline": self.pipeline.config,
            "indexes": [self._index(state, m).describe() for m in INDEX_FACTORIES]
            + [self._semantic_description(collection)]
            + [{"method": "hybrid", "fusion": "reciprocal_rank_fusion", "params": {"k": RRF_K, "candidates": CANDIDATE_DEPTH},
                "combines": ["bm25", "semantic"]}],
        }

    def search(
        self,
        query: str,
        *,
        method: SearchMethod | str = SearchMethod.BM25,
        k: int = DEFAULT_TOP_K,
        collection: str = DEFAULT_COLLECTION,
    ) -> SearchResponse:
        """Top-k fragmentos para ``query``. Una consulta vacía devuelve 0 resultados."""
        started = time.perf_counter()
        validate_k(k)
        try:
            method = SearchMethod(method)
        except ValueError as exc:
            raise UnsupportedMethodError(f"método no admitido: {method}") from exc
        if method not in INDEX_FACTORIES and method not in (SearchMethod.SEMANTIC, SearchMethod.HYBRID):
            raise UnsupportedMethodError(
                f"método no disponible: {method.value}; use {', '.join(self.available_methods())}"
            )
        if method is SearchMethod.HYBRID:
            ranked, query_tokens, version = self._hybrid(query, k, collection)
        else:
            ranked, query_tokens, version = self._ranked(method, query, k, collection)
        return SearchResponse(
            query=query,
            method=method,
            k=k,
            collection=collection,
            index_version=version,
            query_tokens=query_tokens,
            hits=self._hits(ranked, method),
            took_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    def _ranked(
        self, method: SearchMethod, query: str, k: int, collection: str
    ) -> tuple[list[tuple[Chunk, float]], list[str], str]:
        """Fragmentos ordenados de un método simple, tokens de la consulta y versión."""
        if method is SearchMethod.SEMANTIC:
            index = self.semantic.index(collection)
            pairs = index.search(query or "", k) if (query or "").strip() else []
            # coseno > 0, como el resto de métodos (puntuación positiva); se omite
            # un fragmento borrado entre la sincronización y la consulta
            positive = [(chunk_id, score) for chunk_id, score in pairs if score > 0]
            chunks = self.repository.get_chunks_by_ids([chunk_id for chunk_id, _ in positive])
            return [(chunks[cid], score) for cid, score in positive if cid in chunks], [], index.version
        query_tokens = self.pipeline.process(query or "")
        state = self._state(collection)
        positions = self._index(state, method).search(query_tokens, k) if query_tokens else []
        return [(state.corpus.chunks[p], score) for p, score in positions], query_tokens, state.corpus.version

    def _hybrid(self, query: str, k: int, collection: str) -> tuple[list[tuple[Chunk, float]], list[str], str]:
        """BM25 + semántica fusionados con Reciprocal Rank Fusion (DOC-15)."""
        lexical, query_tokens, lexical_version = self._ranked(SearchMethod.BM25, query, CANDIDATE_DEPTH, collection)
        semantic, _, semantic_version = self._ranked(SearchMethod.SEMANTIC, query, CANDIDATE_DEPTH, collection)
        chunks = {chunk.chunk_id: chunk for chunk, _ in lexical + semantic}
        fused = reciprocal_rank_fusion(
            [[c.chunk_id for c, _ in lexical], [c.chunk_id for c, _ in semantic]], k=RRF_K, limit=k
        )
        version = hashlib.sha256(f"hybrid:{RRF_K}:{lexical_version}:{semantic_version}".encode()).hexdigest()[:16]
        return [(chunks[chunk_id], score) for chunk_id, score in fused], query_tokens, version

    def _hits(self, ranked: list[tuple[Chunk, float]], method: SearchMethod) -> list[SearchHit]:
        documents: dict[str, Document] = {}
        hits: list[SearchHit] = []
        for rank, (chunk, score) in enumerate(ranked, start=1):
            document = documents.get(chunk.doc_id)
            if document is None:
                document = self.repository.get_document(chunk.doc_id)
                documents[chunk.doc_id] = document
            hits.append(
                SearchHit(
                    rank=rank,
                    score=round(score, 6),
                    method=method,
                    doc_id=chunk.doc_id,
                    chunk_id=chunk.chunk_id,
                    title=document.title,
                    original_filename=document.original_filename,
                    snippet=make_snippet(chunk.text),
                    page=chunk.page_start,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                )
            )
        return hits
