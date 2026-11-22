"""Resultados de evaluación versionados, solo lectura (DOC-36).

Lee ``evaluation/results/*.json`` tal como están en el repositorio y su
``catalogo.json`` (corpus, anotación, fecha, límites). No recalcula ni
modifica métricas, y no devuelve el detalle por consulta. Son agregados
públicos del proyecto: no requieren sesión.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from backend.app.api.errors import ApiError

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

RESULTS_DIR = Path(__file__).resolve().parents[3] / "evaluation" / "results"
_NAME = re.compile(r"^[a-z0-9_]{1,80}$")
METRICS = ("recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10")
ALPHA = 0.05


def _catalog(directory: Path) -> dict[str, dict[str, Any]]:
    path = directory / "catalogo.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {entry["archivo"]: entry for entry in data.get("conjuntos", [])}


def _summarize(name: str, data: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    methods = list(data.get("methods") or data.get("summary", {}).keys())
    summary = {
        method: {
            subset: {key: values.get(key) for key in ("queries", *METRICS) if key in values}
            for subset, values in (data.get("summary", {}).get(method) or {}).items()
        }
        for method in methods
    }
    first = next(iter(summary.values()), {}).get("all", {})
    engine = data.get("engine") or {}
    significance = data.get("significance")
    readings: list[dict[str, Any]] = []
    if significance:
        for method, comparisons in significance.get("comparisons", {}).items():
            for metric, values in comparisons.items():
                p = values.get("p_value")
                readings.append({
                    "method": method,
                    "metric": metric,
                    "mean_difference": values.get("mean_difference"),
                    "wins": values.get("wins"),
                    "losses": values.get("losses"),
                    "p_value": p,
                    "significant": p is not None and p < ALPHA,
                })
    return {
        "id": name,
        "file": f"evaluation/results/{name}.json",
        "title": meta.get("titulo", name),
        "primary": bool(meta.get("principal")),
        "annotation": meta.get("anotacion", "desconocida"),
        "date": meta.get("fecha"),
        "corpus": meta.get("corpus"),
        "limits": meta.get("limites"),
        "documentation": meta.get("documentacion"),
        "collection": data.get("collection"),
        "queries_file": data.get("queries_file"),
        "split": data.get("split"),
        "depth": data.get("depth"),
        "index_version": data.get("index_version"),
        "chunks": engine.get("chunks"),
        "queries": first.get("queries"),
        "methods": methods,
        "subsets": sorted({subset for values in summary.values() for subset in values}),
        "summary": summary,
        "significance": {
            "baseline": significance.get("baseline"),
            "test": significance.get("test"),
            "alpha": ALPHA,
            "comparisons": readings,
        } if significance else None,
    }


def load_results(directory: Path | None = None) -> list[dict[str, Any]]:
    """Resultados ordenados: primero el principal (anotación humana), después por fecha."""
    directory = RESULTS_DIR if directory is None else directory
    if not directory.is_dir():
        return []
    catalog = _catalog(directory)
    items = []
    for path in sorted(directory.glob("*.json")):
        if path.name == "catalogo.json" or not _NAME.match(path.stem):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or "summary" not in data:
            continue
        items.append(_summarize(path.stem, data, catalog.get(path.name, {})))
    order = {name: position for position, name in enumerate(catalog)}
    # principal primero; después, el orden del catálogo (los no catalogados al final)
    items.sort(key=lambda item: (not item["primary"], order.get(f"{item['id']}.json", len(order)), item["id"]))
    return items


@router.get("", summary="Resultados de evaluación versionados (solo lectura)")
def list_results() -> dict[str, Any]:
    return {"metrics": list(METRICS), "items": load_results()}


@router.get("/{result_id}", summary="Un conjunto de resultados")
def get_result(result_id: str) -> dict[str, Any]:
    if not _NAME.match(result_id):
        raise ApiError(404, "not_found", "resultado no encontrado")
    for item in load_results():
        if item["id"] == result_id:
            return item
    raise ApiError(404, "not_found", "resultado no encontrado")
