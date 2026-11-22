"""Preguntas sobre los documentos con citas verificables (DOC-38).

``POST /ask`` recupera fragmentos (híbrida o BM25) y, si hay un modelo local
configurado (Ollama en 127.0.0.1), genera una respuesta que solo se devuelve
si cita fragmentos realmente recuperados. Sin modelo configurado responde 503
y la búsqueda normal sigue disponible. La generación puede tardar en CPU: el
requisito de menos de 2 s se aplica a la recuperación, no a la generación.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.app.api.errors import ApiError, ErrorResponse
from backend.app.api.search import Collection, get_search_engine
from backend.app.auth.dependencies import require_user, require_user_mutation
from backend.app.rag import RagBusyError, RagConfig, RagProviderError, RagService, RagUnavailableError, build_generator
from backend.app.search.engine import SearchEngine

router = APIRouter(prefix="/ask", tags=["ask"])

DISCLAIMER = (
    "Respuesta generada por un modelo de lenguaje local a partir de los fragmentos citados. "
    "Puede contener errores: verifique cada afirmación en su fuente."
)


class AskMethod(str, Enum):
    hybrid = "hybrid"
    bm25 = "bm25"
    semantic = "semantic"


class AskIn(BaseModel):
    model_config = {"extra": "forbid"}

    question: str = Field(min_length=3, max_length=500)
    collection: Collection = Collection.user
    method: AskMethod = AskMethod.hybrid
    k: int = Field(default=5, ge=1, le=10)


def get_rag_config(request: Request) -> RagConfig:
    config = getattr(request.app.state, "rag_config", None)
    if config is None:
        config = RagConfig.from_env()
        request.app.state.rag_config = config
    return config


def get_rag_service(request: Request, engine: SearchEngine = Depends(get_search_engine)) -> Optional[RagService]:
    service = getattr(request.app.state, "rag_service", None)
    if service is not None:
        return service
    generator = getattr(request.app.state, "rag_generator", None) or build_generator(get_rag_config(request))
    if generator is None:
        return None
    service = RagService(engine, generator)
    request.app.state.rag_service = service
    return service


@router.get("/status", summary="Estado del proveedor de respuestas (sin generar nada)", dependencies=[Depends(require_user)])
def status(request: Request, service: Optional[RagService] = Depends(get_rag_service)) -> dict[str, Any]:
    if service is None:
        return {
            "configured": False,
            "provider": None,
            "message": "No hay un modelo local configurado (DOCUSEARCH_RAG_PROVIDER=ollama). La búsqueda funciona igual.",
        }
    generator = service.generator
    return {"configured": True, "provider": generator.name, "model": generator.model, **generator.status()}


@router.post(
    "",
    summary="Pregunta respondida con citas a fragmentos recuperados",
    responses={
        401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 429: {"model": ErrorResponse},
        502: {"model": ErrorResponse}, 503: {"model": ErrorResponse, "description": "Sin modelo local configurado o sin respuesta"},
    },
)
def ask(
    body: AskIn,
    _: Any = Depends(require_user_mutation),
    service: Optional[RagService] = Depends(get_rag_service),
) -> dict[str, Any]:
    if service is None:
        raise ApiError(
            503, "rag_unavailable",
            "no hay un modelo local configurado para responder preguntas; use la búsqueda (BM25 o híbrida)",
        )
    try:
        result = service.ask(body.question, collection=body.collection.value, k=body.k, method=body.method.value)
    except RagBusyError as exc:
        raise ApiError(429, "rag_busy", str(exc), headers={"Retry-After": "10"}) from exc
    except RagUnavailableError as exc:
        raise ApiError(503, "rag_unreachable", f"{exc}. La búsqueda sigue disponible.") from exc
    except RagProviderError as exc:
        raise ApiError(502, "rag_provider_error", str(exc)) from exc
    result["disclaimer"] = DISCLAIMER
    return result


class FeedbackIn(BaseModel):
    """Opinión sobre una respuesta (DOC-39). No incluye la pregunta ni la respuesta."""

    model_config = {"extra": "forbid"}

    rating: str = Field(pattern="^(util|no_util)$")
    status: str = Field(pattern="^(answered|insufficient_evidence|unsupported|no_evidence)$")
    citations: int = Field(ge=0, le=10)


@router.post("/feedback", status_code=204, summary="Registrar si una respuesta fue útil (sin texto)")
def feedback(body: FeedbackIn, request: Request, _: Any = Depends(require_user_mutation)) -> None:
    """Agrega una línea a ``indexes/rag_feedback.jsonl`` sin la pregunta ni la respuesta."""
    import json
    import time

    settings = request.app.state.settings
    path = settings.paths.indexes_dir / "rag_feedback.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    generator = getattr(getattr(request.app.state, "rag_service", None), "generator", None)
    record = {"ts": int(time.time()), "rating": body.rating, "status": body.status, "citations": body.citations,
              "model": getattr(generator, "model", None)}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
