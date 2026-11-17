"""Servicio de embeddings (DOC-12).

Las pruebas por defecto no descargan el modelo: usan ``HashingEncoder`` y un
modelo simulado con la misma interfaz que ``SentenceTransformer``. Las que
usan el modelo real llevan la marca ``semantic_model`` y solo se ejecutan con
el extra ``semantic`` instalado y ``DOCUSEARCH_TEST_SEMANTIC_MODEL=1``.
"""

from __future__ import annotations

import os
import re

import numpy as np
import pytest

from backend.app.nlp import embeddings
from backend.app.nlp.embeddings import (
    EmbeddingConfig,
    EmbeddingUnavailableError,
    HashingEncoder,
    SentenceTransformerEncoder,
    split_windows,
)

_WORDPIECE = re.compile(r"\w{1,4}|[^\w\s]")


class FakeTokenizer:
    """Tokenizador simulado: trozos de hasta 4 letras y signos, con offsets."""

    def num_special_tokens_to_add(self, pair: bool = False) -> int:
        return 2

    def __call__(self, text: str, add_special_tokens: bool = False, return_offsets_mapping: bool = False):
        offsets = [(m.start(), m.end()) for m in _WORDPIECE.finditer(text)]
        return {"input_ids": list(range(len(offsets))), "offset_mapping": offsets}


class FakeModel:
    """Modelo simulado: registra los segmentos y los codifica con hashing."""

    max_seq_length = 12  # 10 tokens de contenido por ventana

    def __init__(self) -> None:
        self.tokenizer = FakeTokenizer()
        self.calls: list[list[str]] = []
        self._hashing = HashingEncoder(16)

    def get_embedding_dimension(self) -> int:
        return 16

    def encode(self, segments, batch_size, normalize_embeddings, convert_to_numpy, show_progress_bar):
        assert normalize_embeddings and convert_to_numpy
        self.calls.append(list(segments))
        return self._hashing.encode(segments)


def _fake_encoder(long_text: str = "mean") -> tuple[SentenceTransformerEncoder, FakeModel]:
    encoder = SentenceTransformerEncoder(EmbeddingConfig(long_text=long_text))
    model = FakeModel()
    encoder._model = model
    return encoder, model


# --- split_windows ---------------------------------------------------------


def _offsets(text: str) -> list[tuple[int, int]]:
    return FakeTokenizer()(text)["offset_mapping"]


def test_split_windows_respects_limit_and_word_boundaries() -> None:
    text = "fotosintesis convierte energia solar en energia quimica dentro de cloroplastos"
    segments = split_windows(text, _offsets(text), window=6)
    assert all(n <= 6 for _, n in segments)
    assert sum(n for _, n in segments) == len(_offsets(text))
    for segment, _ in segments:  # ninguna palabra partida
        assert all(word in text.split() for word in segment.split())
    assert " ".join(s for s, _ in segments) == text


def test_split_windows_cuts_inside_word_longer_than_window() -> None:
    text = "electroencefalografista"
    segments = split_windows(text, _offsets(text), window=2)
    assert [n for _, n in segments] == [2, 2, 2]
    assert "".join(s for s, _ in segments) == text


def test_split_windows_short_and_empty_text() -> None:
    assert split_windows("hola mundo", _offsets("hola mundo"), window=10) == [("hola mundo", 3)]
    assert split_windows("", [], window=10) == []
    assert split_windows("abc", [(0, 0), (0, 3)], window=5) == [("abc", 1)]  # ignora tokens vacíos
    with pytest.raises(ValueError):
        split_windows("abc", [(0, 3)], window=0)


# --- SentenceTransformerEncoder con modelo simulado -----------------------


def test_encode_long_text_uses_windows_and_normalizes() -> None:
    encoder, model = _fake_encoder()
    long_text = " ".join(f"palabra{i}" for i in range(30))
    vectors = encoder.encode([long_text, "texto corto"])
    assert vectors.shape == (2, 16) and vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-6)
    segments = model.calls[0]
    assert len(segments) > 2  # el texto largo se dividió
    assert all(len(_offsets(s)) <= encoder.max_tokens for s in segments)
    assert segments[-1] == "texto corto"  # un solo lote, en orden


def test_encode_mean_is_token_weighted_average_of_windows() -> None:
    encoder, _ = _fake_encoder()
    text = " ".join(["alfa"] * 10 + ["beta"] * 3)
    windows = split_windows(text, _offsets(text), encoder.max_tokens)
    parts = HashingEncoder(16).encode([s for s, _ in windows])
    expected = (parts * np.array([[n] for _, n in windows], dtype=np.float32)).sum(axis=0)
    expected /= np.linalg.norm(expected)
    assert np.allclose(encoder.encode([text])[0], expected, atol=1e-6)


def test_encode_truncate_sends_whole_text() -> None:
    encoder, model = _fake_encoder("truncate")
    text = " ".join(f"palabra{i}" for i in range(30))
    encoder.encode([text])
    assert model.calls == [[text]]


def test_encode_empty_texts_give_zero_vectors_without_calling_model() -> None:
    encoder, model = _fake_encoder()
    vectors = encoder.encode(["", "   \n ", "<b></b>"])
    assert vectors.shape == (3, 16) and not vectors.any()
    assert model.calls == []
    assert encoder.encode([]).shape == (0, 16)


def test_encode_applies_semantic_pipeline() -> None:
    encoder, model = _fake_encoder()
    encoder.encode(["<p>recupe-\nración</p>"])
    assert model.calls == [["recuperación"]]


def test_config_exposes_model_and_pipeline() -> None:
    encoder, _ = _fake_encoder()
    config = encoder.config
    assert config["model"] == embeddings.MODEL_NAME
    assert config["revision"] == embeddings.MODEL_REVISION and len(config["revision"]) == 40
    assert config["dimension"] == 16 and config["max_tokens"] == 10
    assert config["normalized"] is True and config["long_text"] == "mean"
    assert config["text_pipeline"]["pipeline"] == "semantic"


def test_embedding_config_validation_and_env(monkeypatch, tmp_path) -> None:
    with pytest.raises(ValueError):
        EmbeddingConfig(batch_size=0)
    with pytest.raises(ValueError):
        EmbeddingConfig(long_text="max")
    monkeypatch.setenv(embeddings.MODEL_CACHE_ENV, str(tmp_path))
    monkeypatch.setenv(embeddings.BATCH_SIZE_ENV, "8")
    config = EmbeddingConfig.from_env()
    assert config.cache_dir == tmp_path and config.batch_size == 8 and config.device == "cpu"
    monkeypatch.setenv(embeddings.BATCH_SIZE_ENV, "ocho")
    with pytest.raises(ValueError):
        EmbeddingConfig.from_env()


def test_missing_semantic_extra_raises_clear_error(monkeypatch) -> None:
    monkeypatch.setattr(embeddings, "semantic_available", lambda: False)
    encoder = SentenceTransformerEncoder(EmbeddingConfig())
    with pytest.raises(EmbeddingUnavailableError, match="semantic"):
        encoder.encode(["hola"])


def test_model_load_failure_is_wrapped(monkeypatch) -> None:
    if not embeddings.semantic_available():
        pytest.skip("requiere sentence-transformers instalado")
    import sentence_transformers

    def boom(*args, **kwargs):
        raise OSError("sin red")

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", boom)
    with pytest.raises(EmbeddingUnavailableError, match="sin red"):
        SentenceTransformerEncoder(EmbeddingConfig()).dimension


def test_get_encoder_is_shared_and_lazy(monkeypatch) -> None:
    monkeypatch.setattr(embeddings, "_default_encoder", None)
    first = embeddings.get_encoder()
    assert first is embeddings.get_encoder()
    assert first._model is None  # crear el codificador no carga el modelo


# --- HashingEncoder ---------------------------------------------------------


def test_hashing_encoder_is_deterministic_and_normalized() -> None:
    encoder = HashingEncoder(64)
    texts = ["El dengue lo transmiten mosquitos", "dengue y mosquitos", "La fotosíntesis", ""]
    first, second = encoder.encode(texts), encoder.encode(texts)
    assert np.array_equal(first, second)
    assert np.allclose(np.linalg.norm(first[:3], axis=1), 1.0, atol=1e-6) and not first[3].any()
    assert first[0] @ first[1] > first[0] @ first[2]
    assert encoder.config["encoder"] == "hashing" and encoder.dimension == 64
    with pytest.raises(ValueError):
        HashingEncoder(1)


# --- Modelo real (opcional) ------------------------------------------------

real_model = pytest.mark.skipif(
    not (embeddings.semantic_available() and os.environ.get("DOCUSEARCH_TEST_SEMANTIC_MODEL") == "1"),
    reason="requiere el extra semantic y DOCUSEARCH_TEST_SEMANTIC_MODEL=1 (descarga ~460 MB la primera vez)",
)


@pytest.fixture(scope="module")
def real_encoder() -> SentenceTransformerEncoder:
    return SentenceTransformerEncoder(EmbeddingConfig())


@pytest.mark.semantic_model
@real_model
def test_real_model_config_and_determinism(real_encoder: SentenceTransformerEncoder) -> None:
    assert real_encoder.dimension == 384 and real_encoder.max_tokens == 126
    texts = ["El dengue es una enfermedad viral transmitida por mosquitos.", "Hola"]
    first, second = real_encoder.encode(texts), real_encoder.encode(texts)
    assert first.dtype == np.float32 and np.allclose(first, second, atol=1e-6)
    assert np.allclose(np.linalg.norm(first, axis=1), 1.0, atol=1e-5)


@pytest.mark.semantic_model
@real_model
def test_real_model_captures_paraphrase(real_encoder: SentenceTransformerEncoder) -> None:
    document, paraphrase, unrelated = real_encoder.encode([
        "El dengue es una enfermedad viral transmitida por la picadura de mosquitos Aedes.",
        "infección que contagian los zancudos",
        "La fotosíntesis convierte la luz solar en energía química en las plantas.",
    ])
    assert document @ paraphrase > document @ unrelated + 0.2


@pytest.mark.semantic_model
@real_model
def test_real_model_long_chunk_uses_all_windows(real_encoder: SentenceTransformerEncoder) -> None:
    start = "Los volcanes expulsan lava y ceniza durante una erupción. " * 15
    end = "El café se cultiva en regiones tropicales de montaña. " * 15
    chunk, volcano, coffee = real_encoder.encode([start + end, "erupción volcánica", "cultivo de café"])
    truncating = SentenceTransformerEncoder(EmbeddingConfig(long_text="truncate"))
    truncating._model = real_encoder.model
    truncated = truncating.encode([start + end])[0]
    assert chunk @ coffee > truncated @ coffee  # la parte final cuenta con ventanas
    assert chunk @ volcano > 0.3


# --- CLI --------------------------------------------------------------------


def test_cli_embeddings_reports_config_and_encoding(monkeypatch, capsys, tmp_path) -> None:
    import json

    from backend.app.cli import main as cli_main
    from backend.app.config import Settings
    from backend.app.documents.service import DocumentService

    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(tmp_path / "data"))
    service = DocumentService(Settings.from_env())
    service.ingest("nota.txt", ("palabra " * 450).encode())
    encoder, _ = _fake_encoder()
    monkeypatch.setattr(embeddings, "get_encoder", lambda: encoder)
    assert cli_main(["embeddings", "--collection", "user", "--limit", "2"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["config"]["dimension"] == 16
    assert report["encoding"]["chunks"] == 2 and report["encoding"]["shape"] == [2, 16]


def test_cli_embeddings_without_extra_fails_cleanly(monkeypatch, capsys) -> None:
    from backend.app.cli import main as cli_main

    monkeypatch.setattr(embeddings, "semantic_available", lambda: False)
    monkeypatch.setattr(embeddings, "get_encoder", lambda: SentenceTransformerEncoder(EmbeddingConfig()))
    assert cli_main(["embeddings"]) == 1
    assert "semantic" in capsys.readouterr().err
