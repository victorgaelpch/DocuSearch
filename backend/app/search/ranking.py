"""Utilidades de ranking comunes a todos los métodos (DOC-08)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

DEFAULT_TOP_K = 10
MAX_TOP_K = 100


def validate_k(k: int) -> int:
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= MAX_TOP_K:
        raise ValueError(f"k debe ser un entero entre 1 y {MAX_TOP_K}")
    return k


def top_k(scores: np.ndarray, ids: Sequence[str], k: int) -> list[tuple[int, float]]:
    """Índices y puntuaciones de los ``k`` mejores con puntuación > 0.

    Orden determinista: puntuación descendente y, en empate, ``chunk_id``
    ascendente (independiente del orden de inserción).
    """
    validate_k(k)
    positive = np.flatnonzero(scores > 0)
    if positive.size == 0:
        return []
    keys = np.array([ids[i] for i in positive])
    order = np.lexsort((keys, -scores[positive]))
    selected = positive[order[:k]]
    return [(int(i), float(scores[i])) for i in selected]
