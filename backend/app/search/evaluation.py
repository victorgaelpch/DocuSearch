"""Evaluación de recuperación con consultas anotadas (DOC-09).

Métricas a nivel de **documento** (los fragmentos se agrupan por ``doc_id``
conservando la mejor posición), con relevancia binaria:

* ``Recall@k``: proporción de documentos relevantes en los ``k`` primeros.
* ``MRR@10``: inverso de la posición del primer relevante (0 si no está en
  los 10 primeros).
* ``nDCG@10``: ganancia acumulada descontada normalizada.

Las consultas se resuelven a documentos por título exacto dentro de la
colección; una consulta con títulos inexistentes es un error (evita evaluar
contra relevancias vacías sin darse cuenta).
"""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.documents.repository import DocumentRepository

from .engine import SearchEngine
from .ranking import MAX_TOP_K

CUTOFFS = (1, 5, 10)


@dataclass(frozen=True)
class AnnotatedQuery:
    qid: str
    query: str
    kind: str
    relevant_titles: tuple[str, ...]
    split: str = "test"


def load_queries(path: Path, split: str | None = None) -> tuple[list[AnnotatedQuery], dict[str, Any]]:
    """Carga consultas anotadas; ``split`` filtra por ``dev``/``test`` (sin campo: ``test``)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    queries = [
        AnnotatedQuery(q["id"], q["query"], q.get("type", "unknown"), tuple(q["relevant"]), q.get("split", "test"))
        for q in data["queries"]
    ]
    if len({q.qid for q in queries}) != len(queries):
        raise ValueError("hay identificadores de consulta repetidos")
    if split is not None:
        queries = [q for q in queries if q.split == split]
        if not queries:
            raise ValueError(f"no hay consultas en el conjunto {split!r}")
    return queries, data


def paired_permutation_test(a: Sequence[float], b: Sequence[float], *, samples: int = 10000, seed: int = 0) -> float:
    """p-valor bilateral de la diferencia de medias de dos métodos sobre las mismas consultas.

    Prueba de aleatorización pareada (*sign-flip*): bajo la hipótesis nula
    los dos métodos son intercambiables en cada consulta, así que el signo de
    cada diferencia es aleatorio. Con 16 consultas o menos se enumeran todas
    las combinaciones (exacta); si no, ``samples`` muestras con semilla fija.
    """
    import itertools
    import random

    if len(a) != len(b):
        raise ValueError("las dos listas deben tener la misma longitud")
    diffs = [x - y for x, y in zip(a, b)]
    if not diffs or not any(diffs):
        return 1.0
    observed = abs(sum(diffs))
    tolerance = 1e-12
    if len(diffs) <= 16:
        signs_iter = itertools.product((1, -1), repeat=len(diffs))
        total = 2 ** len(diffs)
    else:
        rng = random.Random(seed)
        signs_iter = ([rng.choice((1, -1)) for _ in diffs] for _ in range(samples))
        total = samples
    extreme = sum(
        1 for signs in signs_iter if abs(sum(sign * d for sign, d in zip(signs, diffs))) >= observed - tolerance
    )
    return extreme / total


def compare_methods(
    report: dict[str, Any], baseline: str, metrics: Sequence[str] = ("mrr@10", "ndcg@10")
) -> dict[str, Any]:
    """Diferencia media, victorias/derrotas y p-valor de cada método frente a ``baseline``."""
    by_method: dict[str, dict[str, dict[str, Any]]] = {}
    for row in report["per_query"]:
        by_method.setdefault(row["method"], {})[row["id"]] = row
    if baseline not in by_method:
        raise ValueError(f"método base no evaluado: {baseline}")
    ids = sorted(by_method[baseline])
    result: dict[str, Any] = {}
    for method, per_id in by_method.items():
        if method == baseline:
            continue
        result[method] = {}
        for metric in metrics:
            a = [per_id[i][metric] for i in ids]
            b = [by_method[baseline][i][metric] for i in ids]
            result[method][metric] = {
                "mean_difference": round(statistics.fmean(x - y for x, y in zip(a, b)), 4),
                "wins": sum(x > y for x, y in zip(a, b)),
                "losses": sum(x < y for x, y in zip(a, b)),
                "p_value": round(paired_permutation_test(a, b), 4),
            }
    return {"baseline": baseline, "test": "paired_permutation", "comparisons": result}


def recall_at(ranking: Sequence[str], relevant: set[str], k: int) -> float:
    return len(set(ranking[:k]) & relevant) / len(relevant) if relevant else 0.0


def reciprocal_rank(ranking: Sequence[str], relevant: set[str], k: int = 10) -> float:
    for position, doc_id in enumerate(ranking[:k], start=1):
        if doc_id in relevant:
            return 1.0 / position
    return 0.0


def ndcg_at(ranking: Sequence[str], relevant: set[str], k: int = 10) -> float:
    dcg = sum(
        1.0 / math.log2(position + 1)
        for position, doc_id in enumerate(ranking[:k], start=1)
        if doc_id in relevant
    )
    ideal = sum(1.0 / math.log2(position + 1) for position in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def document_ranking(chunk_doc_ids: Iterable[str]) -> list[str]:
    """Documentos en orden de su mejor fragmento (sin repetidos)."""
    return list(dict.fromkeys(chunk_doc_ids))


def _title_index(repository: DocumentRepository, collection: str) -> dict[str, str]:
    index: dict[str, str] = {}
    offset = 0
    while batch := repository.list_documents(collection, limit=200, offset=offset):
        for document in batch:
            index[document.title] = document.doc_id
        offset += len(batch)
    return index


def evaluate(
    engine: SearchEngine,
    queries: Sequence[AnnotatedQuery],
    *,
    methods: Sequence[str] = ("tfidf", "bm25"),
    collection: str = "wikipedia_es",
    depth: int = MAX_TOP_K,
) -> dict[str, Any]:
    """Ejecuta las consultas con cada método y agrega las métricas."""
    titles = _title_index(engine.repository, collection)
    missing = sorted({t for q in queries for t in q.relevant_titles if t not in titles})
    if missing:
        raise ValueError(f"títulos relevantes inexistentes en {collection}: {missing}")

    per_query: list[dict[str, Any]] = []
    index_version = None
    for method in methods:
        for query in queries:
            relevant = {titles[t] for t in query.relevant_titles}
            response = engine.search(query.query, method=method, k=depth, collection=collection)
            index_version = response.index_version
            ranking = document_ranking(h.doc_id for h in response.hits)
            row: dict[str, Any] = {
                "id": query.qid,
                "type": query.kind,
                "split": query.split,
                "method": method,
                "mrr@10": reciprocal_rank(ranking, relevant),
                "ndcg@10": ndcg_at(ranking, relevant),
                "took_ms": response.took_ms,
            }
            for cutoff in CUTOFFS:
                row[f"recall@{cutoff}"] = recall_at(ranking, relevant, cutoff)
            per_query.append(row)

    metrics = [f"recall@{c}" for c in CUTOFFS] + ["mrr@10", "ndcg@10"]
    summary: dict[str, Any] = {}
    for method in methods:
        groups = {"all": [r for r in per_query if r["method"] == method]}
        for kind in sorted({q.kind for q in queries}):
            groups[kind] = [r for r in groups["all"] if r["type"] == kind]
        summary[method] = {
            group: {
                "queries": len(rows),
                **{m: round(statistics.fmean(r[m] for r in rows), 4) for m in metrics},
                "mean_ms": round(statistics.fmean(r["took_ms"] for r in rows), 2),
                "max_ms": round(max(r["took_ms"] for r in rows), 2),
            }
            for group, rows in groups.items()
            if rows
        }
    return {
        "collection": collection,
        "index_version": index_version,
        "depth": depth,
        "methods": list(methods),
        "summary": summary,
        "per_query": per_query,
        "engine": engine.describe(collection),
    }


def format_table(report: dict[str, Any]) -> str:
    """Tabla Markdown con el resumen por método y tipo de consulta."""
    lines = [
        "| Método | Consultas | Tipo | Recall@1 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for method, groups in report["summary"].items():
        for group, values in groups.items():
            lines.append(
                f"| {method} | {values['queries']} | {group} | {values['recall@1']:.3f} | "
                f"{values['recall@5']:.3f} | {values['recall@10']:.3f} | "
                f"{values['mrr@10']:.3f} | {values['ndcg@10']:.3f} |"
            )
    return "\n".join(lines)


def benchmark_latency(
    engine: SearchEngine,
    queries: Sequence[str],
    *,
    methods: Sequence[str] = ("bm25", "tfidf"),
    collection: str = "wikipedia_es",
    k: int = 10,
    repeats: int = 5,
) -> dict[str, Any]:
    """Latencia de consultas (ms) con índices ya construidos.

    Mide ``SearchEngine.search`` completo (preprocesamiento de la consulta,
    ranking y armado de resultados), sin HTTP.
    """
    import time

    started = time.perf_counter()
    engine.describe(collection)  # construye corpus e índices (arranque)
    warmup_ms = (time.perf_counter() - started) * 1000
    report: dict[str, Any] = {
        "collection": collection,
        "k": k,
        "repeats": repeats,
        "queries": len(queries),
        "build_ms": round(warmup_ms, 1),
        "methods": {},
    }
    for method in methods:
        samples: list[float] = []
        for _ in range(repeats):
            for query in queries:
                t0 = time.perf_counter()
                engine.search(query, method=method, k=k, collection=collection)
                samples.append((time.perf_counter() - t0) * 1000)
        samples.sort()
        report["methods"][method] = {
            "n": len(samples),
            "p50_ms": round(statistics.median(samples), 2),
            "p95_ms": round(samples[max(0, math.ceil(0.95 * len(samples)) - 1)], 2),
            "max_ms": round(samples[-1], 2),
            "under_2s": samples[-1] < 2000,
        }
    return report
