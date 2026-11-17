"""Índice TF-IDF con similitud coseno (DOC-08).

Usa ``TfidfVectorizer`` de scikit-learn sobre los tokens ya normalizados por
el pipeline léxico (``analyzer`` identidad: no vuelve a tokenizar ni a pasar
a minúsculas). Con normalización L2, el producto punto entre la consulta y
cada fragmento es la similitud coseno.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from .ranking import top_k

TFIDF_PARAMS: dict[str, Any] = {
    "norm": "l2",
    "use_idf": True,
    "smooth_idf": True,
    "sublinear_tf": False,
    "min_df": 1,
}


def _identity(tokens: Sequence[str]) -> Sequence[str]:
    return tokens


class TfidfIndex:
    """Matriz TF-IDF de los fragmentos de una colección."""

    method = "tfidf"

    def __init__(self, documents: Sequence[Sequence[str]], ids: Sequence[str]) -> None:
        from sklearn import __version__ as sklearn_version
        from sklearn.feature_extraction.text import TfidfVectorizer

        if len(documents) != len(ids):
            raise ValueError("documents e ids deben tener la misma longitud")
        self.ids = list(ids)
        self.vectorizer = TfidfVectorizer(
            analyzer=_identity, lowercase=False, dtype=np.float64, **TFIDF_PARAMS
        )
        self.matrix = None
        self.vocabulary_size = 0
        if any(len(d) for d in documents):
            self.matrix = self.vectorizer.fit_transform(list(documents))
            self.vocabulary_size = len(self.vectorizer.vocabulary_)
        self.params = {**TFIDF_PARAMS, "scikit_learn": sklearn_version}

    def __len__(self) -> int:
        return len(self.ids)

    def scores(self, query_tokens: Sequence[str]) -> np.ndarray:
        if self.matrix is None or not query_tokens:
            return np.zeros(len(self.ids))
        query = self.vectorizer.transform([list(query_tokens)])
        if query.nnz == 0:
            return np.zeros(len(self.ids))
        return np.asarray((self.matrix @ query.T).todense()).ravel()

    def search(self, query_tokens: Sequence[str], k: int) -> list[tuple[int, float]]:
        return top_k(self.scores(query_tokens), self.ids, k)

    def describe(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "chunks": len(self.ids),
            "vocabulary": self.vocabulary_size,
            "params": self.params,
        }
