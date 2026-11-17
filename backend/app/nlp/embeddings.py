"""Servicio de embeddings multilingüe en CPU (DOC-12).

Convierte fragmentos y consultas en vectores densos con
``sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`` (licencia
Apache-2.0, 384 dimensiones), base de la búsqueda semántica de v0.2.

Decisiones:

* **Dependencia opcional.** ``sentence-transformers`` (y PyTorch) se instalan
  con el extra ``semantic``; si faltan, la búsqueda léxica sigue funcionando y
  este módulo lanza :class:`EmbeddingUnavailableError` solo al usarlo.
* **Carga perezosa.** El modelo se carga al codificar por primera vez.
* **Revisión fijada** del modelo en Hugging Face para reproducibilidad. La
  caché del modelo vive fuera del repositorio (caché de Hugging Face o
  ``DOCUSEARCH_MODEL_CACHE``).
* **Textos largos por ventanas.** El modelo solo admite 128 tokens y un
  fragmento de 200 palabras en español tiene ~300. En vez de truncar (el
  modelo vería ~43 % del texto), se divide el texto en ventanas que caben,
  se codifica cada una y se promedian ponderando por número de tokens
  (``long_text="mean"``). ``long_text="truncate"`` reproduce el
  comportamiento por defecto de la biblioteca.
* **Vectores L2 normalizados** (``float32``): el producto interno es el coseno.
  Un texto vacío produce el vector cero.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .semantic import SEMANTIC_CONFIG, prepare_semantic

EMBEDDING_VERSION = 1
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
MODEL_CACHE_ENV = "DOCUSEARCH_MODEL_CACHE"
BATCH_SIZE_ENV = "DOCUSEARCH_EMBEDDING_BATCH_SIZE"
DEFAULT_BATCH_SIZE = 32
LONG_TEXT_STRATEGIES = ("mean", "truncate")


class EmbeddingUnavailableError(RuntimeError):
    """El extra ``semantic`` no está instalado o el modelo no se pudo cargar."""


def semantic_available() -> bool:
    """``True`` si ``sentence-transformers`` está instalado (no carga nada)."""
    return importlib.util.find_spec("sentence_transformers") is not None


class Encoder(Protocol):
    """Interfaz común de los codificadores (real y de pruebas)."""

    @property
    def dimension(self) -> int: ...

    @property
    def config(self) -> dict[str, Any]: ...

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


@dataclass(frozen=True)
class EmbeddingConfig:
    """Parámetros del codificador real."""

    model_name: str = MODEL_NAME
    revision: str = MODEL_REVISION
    batch_size: int = DEFAULT_BATCH_SIZE
    long_text: str = "mean"
    cache_dir: Path | None = None
    device: str = field(default="cpu")

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise ValueError("batch_size debe ser mayor que 0")
        if self.long_text not in LONG_TEXT_STRATEGIES:
            raise ValueError(f"long_text debe ser uno de {LONG_TEXT_STRATEGIES}")

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        cache = os.environ.get(MODEL_CACHE_ENV) or None
        raw_batch = os.environ.get(BATCH_SIZE_ENV)
        try:
            batch = int(raw_batch) if raw_batch and raw_batch.strip() else DEFAULT_BATCH_SIZE
        except ValueError as exc:
            raise ValueError(f"{BATCH_SIZE_ENV} debe ser un entero, se recibió {raw_batch!r}") from exc
        return cls(batch_size=batch, cache_dir=Path(cache) if cache else None)


def split_windows(text: str, offsets: Sequence[tuple[int, int]], window: int) -> list[tuple[str, int]]:
    """Divide ``text`` en segmentos de como mucho ``window`` tokens.

    ``offsets`` son los rangos de caracteres de cada token (sin tokens
    especiales). Los cortes se llevan al inicio de la palabra más cercana para
    no partir palabras, salvo que una sola palabra supere la ventana. Devuelve
    ``(segmento, número_de_tokens)``.
    """
    if window < 1:
        raise ValueError("window debe ser mayor que 0")
    tokens = [(start, end) for start, end in offsets if end > start]
    segments: list[tuple[str, int]] = []
    i = 0
    while i < len(tokens):
        j = min(i + window, len(tokens))
        if j < len(tokens):
            cut = j
            # retrocede hasta un token que empiece palabra (hay espacio antes)
            while cut > i + 1 and tokens[cut][0] <= tokens[cut - 1][1]:
                cut -= 1
            if cut > i + 1 or tokens[cut][0] > tokens[cut - 1][1]:
                j = cut
        segment = text[tokens[i][0] : tokens[j - 1][1]].strip()
        if segment:
            segments.append((segment, j - i))
        i = j
    return segments


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0).astype(np.float32)


class SentenceTransformerEncoder:
    """Codificador real con ``sentence-transformers`` en CPU (carga perezosa)."""

    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self.settings = config or EmbeddingConfig.from_env()
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def model(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    self._model = self._load()
        return self._model

    def _load(self) -> Any:
        if not semantic_available():
            raise EmbeddingUnavailableError(
                "Falta el extra 'semantic': python -m pip install -e \".[semantic]\" (ver docs/embeddings.md)"
            )
        from sentence_transformers import SentenceTransformer

        try:
            return SentenceTransformer(
                self.settings.model_name,
                revision=self.settings.revision,
                device=self.settings.device,
                cache_folder=str(self.settings.cache_dir) if self.settings.cache_dir else None,
            )
        except Exception as exc:  # red, caché corrupta, revisión inexistente…
            raise EmbeddingUnavailableError(f"No se pudo cargar el modelo {self.settings.model_name}: {exc}") from exc

    @property
    def dimension(self) -> int:
        return int(self.model.get_embedding_dimension())

    @property
    def max_tokens(self) -> int:
        """Tokens de contenido por ventana (descontando los especiales)."""
        special = self.model.tokenizer.num_special_tokens_to_add(pair=False)
        return int(self.model.max_seq_length) - special

    @property
    def config(self) -> dict[str, Any]:
        return {
            "encoder": "sentence-transformers",
            "version": EMBEDDING_VERSION,
            "model": self.settings.model_name,
            "revision": self.settings.revision,
            "dimension": self.dimension,
            "max_tokens": self.max_tokens,
            "long_text": self.settings.long_text,
            "normalized": True,
            "dtype": "float32",
            "text_pipeline": SEMANTIC_CONFIG,
        }

    def _segments(self, text: str) -> list[tuple[str, int]]:
        if self.settings.long_text == "truncate":
            return [(text, 1)]
        encoded = self.model.tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        return split_windows(text, encoded["offset_mapping"], self.max_tokens)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Matriz ``(len(texts), dimension)`` normalizada, en el orden recibido."""
        prepared = [prepare_semantic(text) for text in texts]
        owners: list[int] = []
        weights: list[float] = []
        segments: list[str] = []
        for index, text in enumerate(prepared):
            for segment, n_tokens in self._segments(text) if text else []:
                owners.append(index)
                weights.append(float(n_tokens))
                segments.append(segment)
        dimension = self.dimension
        result = np.zeros((len(prepared), dimension), dtype=np.float32)
        if not segments:
            return result
        vectors = self.model.encode(
            segments,
            batch_size=self.settings.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        ).astype(np.float32)
        np.add.at(result, owners, vectors * np.asarray(weights, dtype=np.float32)[:, None])
        return _normalize(result)


_TOKEN = re.compile(r"\w+", re.UNICODE)


class HashingEncoder:
    """Codificador determinista **solo para pruebas** y desarrollo sin modelo.

    Proyecta cada palabra (en minúsculas) a una dimensión con un hash estable y
    normaliza. Textos con palabras en común tienen coseno positivo; no captura
    sinónimos ni paráfrasis.
    """

    def __init__(self, dimension: int = 64) -> None:
        if dimension < 2:
            raise ValueError("dimension debe ser al menos 2")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def config(self) -> dict[str, Any]:
        return {"encoder": "hashing", "version": EMBEDDING_VERSION, "dimension": self._dimension,
                "normalized": True, "dtype": "float32", "text_pipeline": SEMANTIC_CONFIG}

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        result = np.zeros((len(texts), self._dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in _TOKEN.findall(prepare_semantic(text).lower()):
                digest = hashlib.blake2b(word.encode("utf-8"), digest_size=8).digest()
                value = int.from_bytes(digest, "little")
                result[row, value % self._dimension] += 1.0 if (value >> 32) & 1 else -1.0
        return _normalize(result)


_default_encoder: SentenceTransformerEncoder | None = None
_default_lock = threading.Lock()


def get_encoder() -> SentenceTransformerEncoder:
    """Codificador real compartido por el proceso (el modelo se carga una vez)."""
    global _default_encoder
    if _default_encoder is None:
        with _default_lock:
            if _default_encoder is None:
                _default_encoder = SentenceTransformerEncoder()
    return _default_encoder
