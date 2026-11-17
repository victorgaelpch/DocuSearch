"""Contrato de resultado de búsqueda (DOC-02).

Define la forma estable de un resultado para que TF-IDF, BM25 y la búsqueda
semántica (DOC-08/09/10 y v0.2) devuelvan lo mismo. Reindexar o cambiar de
método no requiere cambiar este esquema.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.app.documents.models import CHUNK_ID_PATTERN, DOC_ID_PATTERN


class SearchMethod(str, Enum):
    TFIDF = "tfidf"
    BM25 = "bm25"
    SEMANTIC = "semantic"


class SearchHit(BaseModel):
    """Un fragmento recuperado con su procedencia y puntuación."""

    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    score: float
    method: SearchMethod
    doc_id: str = Field(pattern=DOC_ID_PATTERN)
    chunk_id: str = Field(pattern=CHUNK_ID_PATTERN)
    title: str
    original_filename: str
    snippet: str
    page: Optional[int] = Field(default=None, ge=1, description="Página inicial del fragmento")
    page_start: Optional[int] = Field(default=None, ge=1)
    page_end: Optional[int] = Field(default=None, ge=1)
