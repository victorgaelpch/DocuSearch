"""Pipeline semántico: texto para modelos Transformer (DOC-06).

A diferencia del léxico, **no** elimina stopwords, no lematiza, no cambia
mayúsculas ni quita tildes ni puntuación: los modelos de *sentence embeddings*
(p. ej. ``paraphrase-multilingual-MiniLM-L12-v2``, v0.2) aprovechan las palabras
funcionales y el contexto oracional. Solo se limpian artefactos de extracción y
se unen las líneas cortadas dentro de un párrafo (típico de PDF).
"""

from __future__ import annotations

import re

from .normalization import clean_text

PIPELINE_VERSION = 1
_SINGLE_NEWLINE = re.compile(r"(?<!\n)\n(?!\n)")

SEMANTIC_CONFIG = {
    "pipeline": "semantic",
    "version": PIPELINE_VERSION,
    "remove_stopwords": False,
    "lowercase": False,
    "lemmatize": False,
    "joins_wrapped_lines": True,
}


def prepare_semantic(text: str | None) -> str:
    """Texto limpio con párrafos separados por un salto de línea."""
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    joined = _SINGLE_NEWLINE.sub(" ", cleaned)
    paragraphs = [p.strip() for p in joined.split("\n\n")]
    return "\n".join(p for p in paragraphs if p)
