"""Índice BM25 (Okapi) como línea base experimental (DOC-09).

Puntuación de un fragmento ``d`` para la consulta ``q``::

    score(d, q) = Σ_{t ∈ q} idf(t) · tf(t,d) · (k1 + 1)
                                  / (tf(t,d) + k1 · (1 − b + b · |d| / avgdl))

    idf(t) = ln(1 + (N − df(t) + 0.5) / (df(t) + 0.5))

Se usa la variante de idf no negativa (Lucene/Elasticsearch). Los términos
repetidos de la consulta cuentan una sola vez. Implementación propia con
índice invertido y ``numpy``, para que los parámetros sean explícitos y
auditables.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from typing import Any

import numpy as np

from .ranking import top_k

DEFAULT_K1 = 1.5
DEFAULT_B = 0.75


class BM25Index:
    """Índice invertido BM25 sobre documentos ya tokenizados."""

    method = "bm25"

    def __init__(
        self,
        documents: Sequence[Sequence[str]],
        ids: Sequence[str],
        *,
        k1: float = DEFAULT_K1,
        b: float = DEFAULT_B,
    ) -> None:
        if len(documents) != len(ids):
            raise ValueError("documents e ids deben tener la misma longitud")
        if k1 < 0 or not 0 <= b <= 1:
            raise ValueError("se requiere k1 >= 0 y 0 <= b <= 1")
        self.ids = list(ids)
        self.k1 = k1
        self.b = b
        self.lengths = np.array([len(d) for d in documents], dtype=np.float64)
        self.avgdl = float(self.lengths.mean()) if len(documents) and self.lengths.sum() else 0.0
        postings: dict[str, tuple[list[int], list[int]]] = {}
        for position, tokens in enumerate(documents):
            for term, frequency in Counter(tokens).items():
                docs, freqs = postings.setdefault(term, ([], []))
                docs.append(position)
                freqs.append(frequency)
        n = len(documents)
        self.postings = {
            term: (np.array(docs, dtype=np.int64), np.array(freqs, dtype=np.float64))
            for term, (docs, freqs) in postings.items()
        }
        self.idf = {
            term: math.log(1 + (n - len(docs) + 0.5) / (len(docs) + 0.5))
            for term, (docs, _) in self.postings.items()
        }
        if self.avgdl > 0:
            self._norm = k1 * (1 - b + b * self.lengths / self.avgdl)
        else:
            self._norm = np.full(n, k1)

    def __len__(self) -> int:
        return len(self.ids)

    def scores(self, query_tokens: Sequence[str]) -> np.ndarray:
        scores = np.zeros(len(self.ids))
        for term in dict.fromkeys(query_tokens):  # únicos, en orden
            posting = self.postings.get(term)
            if posting is None:
                continue
            docs, freqs = posting
            scores[docs] += self.idf[term] * freqs * (self.k1 + 1) / (freqs + self._norm[docs])
        return scores

    def search(self, query_tokens: Sequence[str], k: int) -> list[tuple[int, float]]:
        return top_k(self.scores(query_tokens), self.ids, k)

    def describe(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "chunks": len(self.ids),
            "vocabulary": len(self.postings),
            "params": {
                "k1": self.k1,
                "b": self.b,
                "idf": "ln(1 + (N - df + 0.5) / (df + 0.5))",
                "avgdl": round(self.avgdl, 3),
                "query_terms": "unique",
            },
        }
