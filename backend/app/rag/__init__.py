"""Preguntas con respuestas respaldadas por fragmentos (RAG local opcional, DOC-38)."""

from .providers import RagConfig, RagProviderError, RagUnavailableError, build_generator, validate_local_url
from .service import NO_EVIDENCE_TOKEN, RagBusyError, RagService, build_prompt, extract_citations

__all__ = [
    "NO_EVIDENCE_TOKEN",
    "RagBusyError",
    "RagConfig",
    "RagProviderError",
    "RagService",
    "RagUnavailableError",
    "build_generator",
    "build_prompt",
    "extract_citations",
    "validate_local_url",
]
