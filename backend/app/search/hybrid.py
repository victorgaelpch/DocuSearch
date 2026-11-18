"""Fusión de rankings para la búsqueda híbrida (DOC-15).

Reciprocal Rank Fusion (Cormack, Clarke y Büttcher, SIGIR 2009)::

    RRF(d) = Σ_m  1 / (k + rank_m(d))

``rank_m(d)`` es la posición (desde 1) de ``d`` en la lista del método ``m``;
si ``d`` no aparece en esa lista, no suma. Solo usa posiciones, así que no
hace falta normalizar puntuaciones de escalas distintas (BM25 no acotado,
coseno en [-1, 1]).

``k = 60`` es el valor del artículo original, fijado **antes** de evaluar y
sin ajustarlo con las consultas de prueba.
"""

from __future__ import annotations

from collections.abc import Sequence

RRF_K = 60
CANDIDATE_DEPTH = 100


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], *, k: int = RRF_K, limit: int | None = None
) -> list[tuple[str, float]]:
    """Fusiona listas ordenadas de identificadores.

    Devuelve ``(id, puntuación RRF)`` de mayor a menor; los empates se
    deshacen por identificador para que el orden sea reproducible. Un
    identificador repetido dentro de una misma lista cuenta solo en su mejor
    posición.
    """
    if k < 0:
        raise ValueError("k debe ser mayor o igual que 0")
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for position, item in enumerate(ranking, start=1):
            if item in seen:
                continue
            seen.add(item)
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + position)
    fused = sorted(scores.items(), key=lambda pair: (-round(pair[1], 12), pair[0]))
    return fused if limit is None else fused[:limit]
