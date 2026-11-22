"""Fixtures compartidas."""

from __future__ import annotations

import os

import pytest

# Un .env local del desarrollador no debe cambiar el resultado de las pruebas (DOC-34).
os.environ["DOCUSEARCH_ENV_FILE"] = os.path.join(os.path.dirname(__file__), "no-existe.env")

from backend.app.nlp.lexical import LexicalPipeline, get_lexical_pipeline


@pytest.fixture(scope="session")
def lexical_pipeline() -> LexicalPipeline:
    """Pipeline léxico cargado una sola vez por sesión (spaCy es costoso)."""
    return get_lexical_pipeline()
