"""Pipeline léxico para TF-IDF y BM25 (DOC-06).

Pasos: ``clean_text`` → tokenización spaCy → filtrado de puntuación, espacios,
URLs y stopwords → lematización con ``es_core_news_sm`` → minúsculas →
(opcional) eliminación de tildes conservando la ``ñ``.

El mismo objeto procesa documentos y consultas, de modo que ambos lados del
índice comparten exactamente la misma normalización.

Si el modelo ``es_core_news_sm`` no está instalado y ``require_model`` es
``False``, se usa el tokenizador básico de spaCy **sin lematización** y se
registra en ``config`` (``"lemmatizer": null``), para que los índices
construidos así no se confundan con los lematizados.

**Formas superficiales (versión 2).** El lematizador de spaCy depende de la
etiqueta gramatical, y en consultas cortas sin contexto la asigna mal
(``dengue`` → ``denguir``, ``lava`` → ``lavar``). Por eso, cuando hay
lematizador, cada palabra produce dos términos: su lema y su forma
superficial normalizada con prefijo ``=`` (``"lava"`` y ``"=lava"``). Si la
consulta se lematiza mal, la forma exacta sigue coincidiendo con el
documento; las coincidencias exactas pesan algo más que las solo por lema.
Se desactiva con ``index_surface_forms=False``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .normalization import clean_text, strip_accents

logger = logging.getLogger(__name__)

PIPELINE_VERSION = 2
SURFACE_PREFIX = "="
DEFAULT_SPACY_MODEL = "es_core_news_sm"

# Palabras de la lista de spaCy que en búsqueda sí aportan contenido.
CONTENT_WORDS_KEPT = frozenset(
    {
        "estado", "estados", "trabajo", "trabajar", "trabaja", "trabajan",
        "grande", "grandes", "gran", "nuevo", "nueva", "nuevos", "nuevas",
        "verdad", "verdadero", "verdadera", "uso", "usar", "usa", "usan",
        "tiempo", "día", "días", "fin", "lugar", "lado", "parte", "manera",
        "modo", "valor", "mayor", "menor", "general", "mejor", "peor",
        "bueno", "buena", "buenos", "buenas", "malo", "mala", "medio",
        "conocer", "realizar", "primero", "primera", "segundo", "segunda",
        "tercero", "tercera", "posible", "diferente", "diferentes",
    }
)


class SpacyModelNotAvailable(RuntimeError):
    """El modelo de spaCy solicitado no está instalado."""


def _load_stopwords() -> frozenset[str]:
    from spacy.lang.es.stop_words import STOP_WORDS

    return frozenset(w.lower() for w in STOP_WORDS) - CONTENT_WORDS_KEPT


@dataclass
class LexicalPipeline:
    """Normalización léxica reutilizable para documentos y consultas."""

    model_name: str = DEFAULT_SPACY_MODEL
    lemmatize: bool = True
    remove_stopwords: bool = True
    fold_accents: bool = True
    min_token_length: int = 1
    index_surface_forms: bool = True
    require_model: bool = False
    batch_size: int = 64
    _nlp: Any = field(default=None, init=False, repr=False)
    _stopwords: frozenset[str] = field(default_factory=frozenset, init=False, repr=False)
    _lemmatizer_available: bool = field(default=False, init=False, repr=False)
    _model_version: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        import spacy

        self._stopwords = _load_stopwords() if self.remove_stopwords else frozenset()
        self._stopwords_folded = frozenset(strip_accents(w) for w in self._stopwords)
        if self.lemmatize:
            try:
                self._nlp = spacy.load(self.model_name, disable=["parser", "ner"])
                self._lemmatizer_available = True
                self._model_version = self._nlp.meta.get("version")
            except OSError as exc:
                if self.require_model:
                    raise SpacyModelNotAvailable(
                        f"instale el modelo con: python -m spacy download {self.model_name}"
                    ) from exc
                logger.warning(
                    "Modelo spaCy %s no disponible; se usa tokenización sin lematizar",
                    self.model_name,
                )
        if self._nlp is None:
            self._nlp = spacy.blank("es")

    # -- configuración ---------------------------------------------------------
    @property
    def lemmatizer_available(self) -> bool:
        return self._lemmatizer_available

    @property
    def config(self) -> dict[str, Any]:
        """Parámetros que identifican la normalización (se guardan con el índice)."""
        return {
            "pipeline": "lexical",
            "version": PIPELINE_VERSION,
            "lemmatizer": (
                f"{self.model_name}-{self._model_version}" if self._lemmatizer_available else None
            ),
            "remove_stopwords": self.remove_stopwords,
            "stopwords": f"spacy-es-minus-content-words:{len(self._stopwords)}",
            "lowercase": True,
            "fold_accents": self.fold_accents,
            "min_token_length": self.min_token_length,
            "surface_forms": self._emit_surface,
        }

    @property
    def _emit_surface(self) -> bool:
        return self.index_surface_forms and self._lemmatizer_available

    # -- procesamiento -------------------------------------------------------
    def _tokens_from_doc(self, doc: Any) -> list[str]:
        tokens: list[str] = []
        for token in doc:
            if token.is_space or token.is_punct or token.like_url or token.like_email:
                continue
            surface = token.lower_
            if not any(ch.isalnum() for ch in surface):
                continue
            if self.remove_stopwords and surface in self._stopwords:
                continue
            term = token.lemma_.lower() if self._lemmatizer_available and token.lemma_ else surface
            term = term.strip()
            if self.fold_accents:
                term = strip_accents(term)
            if self.remove_stopwords and (
                term in self._stopwords or term in self._stopwords_folded
            ):
                continue
            if len(term) < self.min_token_length or not any(ch.isalnum() for ch in term):
                continue
            tokens.append(term)
            if self._emit_surface:
                form = strip_accents(surface) if self.fold_accents else surface
                tokens.append(SURFACE_PREFIX + form)
        return tokens

    @staticmethod
    def lemmas(tokens: Iterable[str]) -> list[str]:
        """Solo los lemas (sin formas superficiales), p. ej. para mostrar."""
        return [t for t in tokens if not t.startswith(SURFACE_PREFIX)]

    def process(self, text: str | None) -> list[str]:
        """Tokens normalizados de un texto (lista vacía si no hay contenido)."""
        cleaned = clean_text(text)
        if not cleaned:
            return []
        return self._tokens_from_doc(self._nlp(cleaned))

    def process_many(self, texts: Iterable[str | None]) -> list[list[str]]:
        """Versión por lotes (más rápida) de ``process``; conserva el orden."""
        cleaned = [clean_text(t) for t in texts]
        results: list[list[str]] = [[] for _ in cleaned]
        non_empty = [(i, t) for i, t in enumerate(cleaned) if t]
        docs = self._nlp.pipe((t for _, t in non_empty), batch_size=self.batch_size)
        for (index, _), doc in zip(non_empty, docs):
            results[index] = self._tokens_from_doc(doc)
        return results


_DEFAULT: LexicalPipeline | None = None


def get_lexical_pipeline() -> LexicalPipeline:
    """Instancia compartida (cargar spaCy es costoso)."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = LexicalPipeline()
    return _DEFAULT
