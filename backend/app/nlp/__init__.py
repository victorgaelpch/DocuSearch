"""Preprocesamiento de texto en español (DOC-06)."""

from .lexical import LexicalPipeline, SpacyModelNotAvailable, get_lexical_pipeline
from .normalization import clean_text, is_blank, strip_accents
from .semantic import SEMANTIC_CONFIG, prepare_semantic

__all__ = [
    "SEMANTIC_CONFIG",
    "LexicalPipeline",
    "SpacyModelNotAvailable",
    "clean_text",
    "get_lexical_pipeline",
    "is_blank",
    "prepare_semantic",
    "strip_accents",
]
