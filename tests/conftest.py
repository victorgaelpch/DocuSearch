"""Fixtures compartidas."""

from __future__ import annotations

import pytest

from backend.app.nlp.lexical import LexicalPipeline, get_lexical_pipeline


@pytest.fixture(scope="session")
def lexical_pipeline() -> LexicalPipeline:
    """Pipeline léxico cargado una sola vez por sesión (spaCy es costoso)."""
    return get_lexical_pipeline()
