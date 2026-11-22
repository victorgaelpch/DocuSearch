"""Informe reproducible de rendimiento local (DOC-40).

Mide sobre una copia temporal de la demostración (``demo/documentos``) o sobre
una colección ya cargada:

* coste de ingesta por documento (extracción, OCR si aplica, fragmentación);
* arranque en frío: primera búsqueda por método (carga de spaCy/modelo y
  construcción del índice), separada de las consultas en caliente;
* latencia en caliente p50/p95/máx por método a través de la pila HTTP
  completa (middleware de seguridad y registro incluidos);
* memoria residente y datos de la máquina, para poder comparar.

Uso: ``python -m backend.app.cli report [--repeats 5] [--output informe.json]``.
"""

from __future__ import annotations

import json
import os
import platform
import secrets
import statistics
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from backend.app.config import REPO_ROOT, Settings

DEMO_DIR = REPO_ROOT / "demo"


def machine_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "gpu": "no usada",
    }
    try:
        import psutil

        info["ram_gb"] = round(psutil.virtual_memory().total / 1024**3, 1)
    except Exception:  # noqa: BLE001 — psutil es opcional
        try:
            info["ram_gb"] = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3, 1)
        except (ValueError, OSError, AttributeError):
            info["ram_gb"] = None
    return info


def _quantiles(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p50_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))], 2),
        "max_ms": round(ordered[-1], 2),
    }


def run_report(*, repeats: int = 5, methods: list[str] | None = None, data_dir: Path | None = None) -> dict[str, Any]:
    from fastapi.testclient import TestClient

    from backend.app.auth.passwords import hash_password
    from backend.app.main import create_app
    from backend.app.nlp import embeddings
    from backend.app.observability import process_memory_mb

    queries = [q["consulta"] for q in json.loads((DEMO_DIR / "consultas.json").read_text(encoding="utf-8"))["lexicas"]]
    methods = methods or ["bm25", "tfidf"] + (["semantic", "hybrid"] if embeddings.semantic_available() else [])
    temporary = data_dir is None
    root = Path(tempfile.mkdtemp(prefix="docusearch-report-")) if temporary else data_dir
    password = secrets.token_urlsafe(18)
    settings = replace(Settings.from_env(root), admin_password_hash=hash_password(password))
    report: dict[str, Any] = {"machine": machine_info(), "conditions": {
        "repeats": repeats, "queries": len(queries), "methods": methods, "k": 10,
        "corpus": "demostración sintética (demo/documentos)" if temporary else f"colección user en {root}",
        "http": "pila completa con TestClient (sin red)",
    }}
    started = time.perf_counter()
    client = TestClient(create_app(settings))
    report["startup_ms"] = round((time.perf_counter() - started) * 1000, 2)
    response = client.post("/auth/login", json={"username": settings.admin_username, "password": password})
    response.raise_for_status()
    headers = {"X-CSRF-Token": response.json()["csrf_token"]}

    ingestion = []
    if temporary:
        for path in sorted((DEMO_DIR / "documentos").iterdir()):
            if path.suffix.lower() not in {".pdf", ".docx", ".txt"}:
                continue
            t0 = time.perf_counter()
            res = client.post("/documents", files={"file": (path.name, path.read_bytes())}, headers=headers)
            ingestion.append({"file": path.name, "bytes": path.stat().st_size, "status": res.json().get("extraction_status"),
                              "chunks": res.json().get("chunk_count"), "ms": round((time.perf_counter() - t0) * 1000, 2)})
    report["ingestion"] = ingestion

    results: dict[str, Any] = {}
    for method in methods:
        t0 = time.perf_counter()
        first = client.get("/search", params={"q": queries[0], "method": method})
        cold_ms = round((time.perf_counter() - t0) * 1000, 2)
        if first.status_code != 200:
            results[method] = {"error": first.json().get("error", {}).get("message")}
            continue
        warm: list[float] = []
        engine: list[float] = []
        for _ in range(repeats):
            for query in queries:
                t0 = time.perf_counter()
                res = client.get("/search", params={"q": query, "method": method})
                warm.append((time.perf_counter() - t0) * 1000)
                engine.append(res.json()["took_ms"])
        results[method] = {"cold_first_query_ms": cold_ms, "warm_http": _quantiles(warm), "warm_engine": _quantiles(engine)}
    report["search"] = results
    # el recuento va después: consultar el índice antes lo construiría y falsearía la medida en frío
    corpus = client.get("/search/index").json()
    report["corpus"] = {"documents": client.get("/documents", params={"limit": 1}).json()["total"], "chunks": corpus["chunks"]}
    report["memory_mb"] = process_memory_mb()
    report["within_2s"] = all(r.get("warm_http", {}).get("p95_ms", 0) < 2000 for r in results.values() if "warm_http" in r)
    return report


def format_report(report: dict[str, Any]) -> str:
    m = report["machine"]
    lines = [
        f"Máquina: {m['platform']}, Python {m['python']}, {m['cpu_count']} CPU, RAM {m.get('ram_gb')} GB, sin GPU",
        f"Corpus: {report['conditions']['corpus']}: {report['corpus']['documents']} documentos, {report['corpus']['chunks']} fragmentos",
        f"Crear la aplicación: {report['startup_ms']} ms (los modelos se cargan en la primera consulta); memoria al final: {report['memory_mb']} MB",
        "",
        "Ingesta:",
    ]
    lines += [f"  {i['file']:<28} {i['status']:<12} {i['chunks']} fragmento(s)  {i['ms']} ms" for i in report["ingestion"]]
    lines += ["", f"{'Método':<10} {'1.ª consulta (frío)':>20} {'p50 HTTP':>10} {'p95 HTTP':>10} {'máx HTTP':>10} {'p50 motor':>10}"]
    for method, r in report["search"].items():
        if "error" in r:
            lines.append(f"{method:<10} no disponible: {r['error']}")
            continue
        w, e = r["warm_http"], r["warm_engine"]
        lines.append(f"{method:<10} {r['cold_first_query_ms']:>17} ms {w['p50_ms']:>7} ms {w['p95_ms']:>7} ms {w['max_ms']:>7} ms {e['p50_ms']:>7} ms")
    lines += ["", "Búsqueda en caliente < 2 s: " + ("sí" if report["within_2s"] else "NO")]
    return "\n".join(lines)
