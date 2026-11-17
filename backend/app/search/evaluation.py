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


def load_queries(path: Path) -> tuple[list[AnnotatedQuery], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    queries = [
        AnnotatedQuery(q["id"], q["query"], q.get("type", "unknown"), tuple(q["relevant"]))
        for q in data["queries"]
    ]
    if len({q.qid for q in queries}) != len(queries):
        raise ValueError("hay identificadores de consulta repetidos")
    return queries, data


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
