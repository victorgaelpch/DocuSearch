"""Pruebas del preprocesamiento léxico y semántico (DOC-06)."""

from __future__ import annotations

import pytest

from backend.app.nlp import (
    LexicalPipeline,
    SpacyModelNotAvailable,
    clean_text,
    is_blank,
    prepare_semantic,
    strip_accents,
)

try:
    import spacy

    spacy.load("es_core_news_sm")
    HAS_MODEL = True
except OSError:  # pragma: no cover - depende del entorno
    HAS_MODEL = False

needs_model = pytest.mark.skipif(not HAS_MODEL, reason="es_core_news_sm no instalado")


@pytest.fixture(scope="module")
def lexical() -> LexicalPipeline:
    return LexicalPipeline()


# -- normalización común ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  hola\t\tmundo  ", "hola mundo"),
        ("<p>Texto <b>importante</b></p>", "Texto importante"),
        ("Tom &amp; Jerry &lt;3", "Tom & Jerry <3"),
        ("a < b y c > d", "a < b y c > d"),  # no es marcado
        ("recupe-\nración", "recuperación"),
        ("ﬁnanzas y ﬂujo", "finanzas y flujo"),
        ("pala­bra​", "palabra"),
        ("éxito", "éxito"),  # NFC
        ("uno\r\n\r\n\r\n\r\ndos", "uno\n\ndos"),
        ("ctrl\x07char", "ctrl char"),
        ("<!-- comentario -->visible", "visible"),
    ],
)
def test_clean_text(raw: str, expected: str) -> None:
    assert clean_text(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "\n\t", "<br/>", "​﻿"])
def test_blank_inputs(raw) -> None:
    assert clean_text(raw) == ""
    assert is_blank(raw)


def test_strip_accents_keeps_enye() -> None:
    assert strip_accents("búsqueda pingüino AÑO Canción") == "busqueda pinguino AÑO Cancion"


# -- pipeline léxico -------------------------------------------------------------


def test_lexical_removes_stopwords_punctuation_and_lowercases(lexical: LexicalPipeline) -> None:
    tokens = lexical.process("¡La Búsqueda de los DOCUMENTOS, en español!")
    assert "la" not in tokens and "de" not in tokens and "los" not in tokens
    assert all(t == t.lower() for t in tokens)
    assert not any(t in {"¡", "!", ","} for t in tokens)
    assert "busqueda" in tokens and "espanol" not in tokens and "español" in tokens


def test_lexical_handles_empty_and_stopword_only_text(lexical: LexicalPipeline) -> None:
    assert lexical.process("") == []
    assert lexical.process(None) == []
    assert lexical.process("el de la que y") == []
    assert lexical.process("¿?!... ---") == []


def test_lexical_ignores_urls_and_markup(lexical: LexicalPipeline) -> None:
    tokens = lexical.process("Visita <a href='x'>https://ejemplo.org/ruta</a> sobre bibliotecas")
    assert not any("http" in t or "ejemplo" in t for t in tokens)
    assert any(t.startswith("bibliotec") for t in tokens)


def test_lexical_keeps_numbers_and_content_words(lexical: LexicalPipeline) -> None:
    tokens = lexical.process("El trabajo de 1492 en los Estados")
    assert "1492" in tokens
    assert "trabajo" in tokens


@needs_model
def test_lexical_lemmatizes_with_spacy(lexical: LexicalPipeline) -> None:
    assert lexical.lemmatizer_available
    tokens = lexical.process("Los niños estaban corriendo por las calles")
    assert lexical.lemmas(tokens) == ["niño", "correr", "calle"]
    assert tokens == ["niño", "=niños", "correr", "=corriendo", "calle", "=calles"]
    assert lexical.config["lemmatizer"].startswith("es_core_news_sm-")


@needs_model
def test_documents_and_queries_share_normalization(lexical: LexicalPipeline) -> None:
    document = lexical.process("Las bibliotecas digitales almacenan documentos antiguos.")
    query = lexical.process("biblioteca digital documento")
    assert set(lexical.lemmas(query)) <= set(document)
    # una consulta sin tildes coincide con un texto con tildes
    assert set(lexical.process("informacion")) <= set(lexical.process("Información"))


@needs_model
@pytest.mark.parametrize(
    ("query", "sentence"),
    [
        ("dengue", "El dengue es una infección transmitida por mosquitos."),
        ("lava", "Los volcanes expulsan lava durante la erupción."),
        ("embeddings", "Los embeddings representan el significado de las oraciones."),
        ("capo", "El capo se coloca en el mástil de la guitarra."),
    ],
)
def test_short_queries_match_despite_wrong_pos_tagging(
    lexical: LexicalPipeline, query: str, sentence: str
) -> None:
    """Regresión (DOC-11): sin contexto, spaCy etiqueta 'dengue' o 'lava' como verbos."""
    assert set(lexical.process(query)) & set(lexical.process(sentence))


def test_surface_forms_can_be_disabled() -> None:
    plain = LexicalPipeline(index_surface_forms=False)
    assert not any(t.startswith("=") for t in plain.process("Los volcanes expulsan lava"))
    assert plain.config["surface_forms"] is False


@needs_model
def test_lexical_does_not_match_synonyms(lexical: LexicalPipeline) -> None:
    """Limitación esperada que motiva la búsqueda semántica (v0.2)."""
    assert not set(lexical.process("automóvil")) & set(lexical.process("coche"))


def test_process_many_preserves_order_and_empties(lexical: LexicalPipeline) -> None:
    texts = ["primer texto sobre gatos", "", "segundo texto sobre perros", None]
    batch = lexical.process_many(texts)
    assert batch == [lexical.process(t) for t in texts]
    assert batch[1] == [] and batch[3] == []


def test_noisy_pdf_like_text(lexical: LexicalPipeline) -> None:
    noisy = "Proce-\nsamiento   del   lenguaje\n\n\n\nnatu-\nral  \x0c pág. 3"
    tokens = lexical.process(noisy)
    assert any(t.startswith("procesamiento") for t in tokens)
    assert "natural" in tokens


def test_configuration_is_explicit() -> None:
    pipeline = LexicalPipeline(lemmatize=False, fold_accents=False, remove_stopwords=False)
    assert pipeline.config["lemmatizer"] is None
    assert pipeline.process("La Canción") == ["la", "canción"]


def test_missing_model_fallback_and_strict_mode() -> None:
    fallback = LexicalPipeline(model_name="modelo_inexistente_xx")
    assert not fallback.lemmatizer_available
    assert fallback.config["lemmatizer"] is None
    assert fallback.process("Los niños corriendo") == ["niños", "corriendo"]
    with pytest.raises(SpacyModelNotAvailable):
        LexicalPipeline(model_name="modelo_inexistente_xx", require_model=True)


# -- pipeline semántico ----------------------------------------------------------


def test_semantic_preserves_function_words_case_and_punctuation() -> None:
    text = "¿Qué es la Recuperación de Información? Es el proceso de encontrar documentos."
    assert prepare_semantic(text) == text


def test_semantic_joins_wrapped_lines_but_keeps_paragraphs() -> None:
    raw = "Primera línea\ncontinúa aquí.\n\nNuevo párrafo con recupe-\nración."
    assert prepare_semantic(raw) == "Primera línea continúa aquí.\nNuevo párrafo con recuperación."


def test_semantic_cleans_markup_and_blank() -> None:
    assert prepare_semantic("<p>Hola &amp; adiós</p>") == "Hola & adiós"
    assert prepare_semantic("   ") == ""
    assert prepare_semantic(None) == ""
