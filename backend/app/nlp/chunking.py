"""Fragmentación de documentos en ventanas de palabras (DOC-07).

Configuración por defecto, según el documento académico: **200 palabras con
30 de solapamiento** (paso de 170 palabras).

* Una "palabra" es una secuencia de caracteres sin espacios (``\\S+``) del
  texto extraído original, así los offsets apuntan exactamente al texto
  devuelto por el lector y la página se recupera con
  ``ExtractionResult.page_for_offset``.
* El texto del fragmento es el corte literal ``text[char_start:char_end]``;
  la limpieza léxica/semántica se aplica después, al indexar.
* El proceso es determinista (no hay azar): mismo texto + misma
  configuración ⇒ mismos fragmentos e IDs.
* No se generan fragmentos vacíos; un texto menor que un fragmento produce
  un único fragmento; la última ventana no repite una cola ya cubierta.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Optional

from backend.app.documents.models import Chunk

DEFAULT_CHUNK_SIZE = 200
DEFAULT_CHUNK_OVERLAP = 30
CHUNKER_VERSION = 1
_WORD = re.compile(r"\S+")


@dataclass(frozen=True)
class ChunkingConfig:
    chunk_size: int = DEFAULT_CHUNK_SIZE
    overlap: int = DEFAULT_CHUNK_OVERLAP

    def __post_init__(self) -> None:
        if self.chunk_size < 1:
            raise ValueError("chunk_size debe ser >= 1")
        if not 0 <= self.overlap < self.chunk_size:
            raise ValueError("overlap debe cumplir 0 <= overlap < chunk_size")

    @property
    def step(self) -> int:
        return self.chunk_size - self.overlap

    def as_dict(self) -> dict[str, Any]:
        return {"version": CHUNKER_VERSION, **asdict(self)}


def chunk_text(
    text: str,
    doc_id: str,
    config: ChunkingConfig | None = None,
    page_for_offset: Optional[Callable[[int], Optional[int]]] = None,
) -> list[Chunk]:
    """Divide ``text`` en fragmentos solapados con procedencia."""
    config = config or ChunkingConfig()
    words = [(m.start(), m.end()) for m in _WORD.finditer(text or "")]
    if not words:
        return []
    chunks: list[Chunk] = []
    total = len(words)
    for ordinal, first in enumerate(range(0, total, config.step)):
        last = min(first + config.chunk_size, total) - 1
        start, end = words[first][0], words[last][1]
        page_start = page_end = None
        if page_for_offset is not None:
            page_start, page_end = page_for_offset(start), page_for_offset(end - 1)
            if page_start is None or page_end is None:
                page_start = page_end = None
        chunks.append(
            Chunk.new(
                doc_id=doc_id,
                ordinal=ordinal,
                text=text[start:end],
                char_start=start,
                char_end=end,
                page_start=page_start,
                page_end=page_end,
            )
        )
        if last == total - 1:
            break
    return chunks


def chunk_extraction(result: Any, doc_id: str, config: ChunkingConfig | None = None) -> list[Chunk]:
    """Fragmenta un ``ExtractionResult`` de DOC-03 conservando páginas."""
    return chunk_text(result.text, doc_id, config, page_for_offset=result.page_for_offset)
