"""Resultados de evaluación versionados, solo lectura (DOC-36)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api import evaluation as evaluation_api
from backend.app.config import Settings
from backend.app.main import create_app

RESULTS = Path(__file__).resolve().parents[1] / "evaluation" / "results"


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings.from_env(tmp_path / "data")))


def test_miracl_is_first_and_marked_as_human(client: TestClient) -> None:
    items = client.get("/evaluation").json()["items"]
    first = items[0]
    assert first["id"] == "miracl_es_dev" and first["primary"] and first["annotation"] == "humana"
    assert first["queries"] == 648 and first["chunks"] == 6828
    assert "no es el corpus MIRACL completo" in first["corpus"]
    assert all(item["annotation"] == "propia" for item in items[1:])
    assert items[1]["id"] == "wikipedia_es_v2_test"  # orden del catálogo
    assert len(items) == len([p for p in RESULTS.glob("*.json") if p.name != "catalogo.json"])


def test_numbers_match_versioned_files_exactly(client: TestClient) -> None:
    for item in client.get("/evaluation").json()["items"]:
        raw = json.loads((RESULTS / f"{item['id']}.json").read_text(encoding="utf-8"))
        for method in raw["methods"]:
            for subset, values in raw["summary"][method].items():
                for metric in ("recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10"):
                    assert item["summary"][method][subset][metric] == values[metric]
        assert "per_query" not in item


def test_significance_reading_comes_from_p_values(client: TestClient) -> None:
    miracl = client.get("/evaluation/miracl_es_dev").json()
    sig = {(c["method"], c["metric"]): c for c in miracl["significance"]["comparisons"]}
    assert miracl["significance"]["baseline"] == "bm25"
    assert sig[("semantic", "ndcg@10")]["significant"] is False  # la semántica sola no supera a BM25
    assert sig[("hybrid", "ndcg@10")]["significant"] is True and sig[("hybrid", "ndcg@10")]["mean_difference"] > 0
    assert miracl["summary"]["hybrid"]["all"]["ndcg@10"] == 0.7523 or round(miracl["summary"]["hybrid"]["all"]["ndcg@10"], 3) == 0.752


def test_empty_or_broken_results_do_not_fail(tmp_path: Path, monkeypatch, client: TestClient) -> None:
    (tmp_path / "roto.json").write_text("{no es json", encoding="utf-8")
    (tmp_path / "otro.json").write_text(json.dumps({"sin": "summary"}), encoding="utf-8")
    assert evaluation_api.load_results(tmp_path) == []
    assert evaluation_api.load_results(tmp_path / "no-existe") == []
    monkeypatch.setattr(evaluation_api, "RESULTS_DIR", tmp_path)
    assert evaluation_api.load_results() == []


def test_unknown_or_unsafe_ids(client: TestClient) -> None:
    assert client.get("/evaluation/no_existe").status_code == 404
    assert client.get("/evaluation/..%2Fcatalogo").status_code == 404
    assert client.get("/evaluation/catalogo").status_code == 404


def test_evaluation_is_public_and_not_cached_as_private(client: TestClient) -> None:
    response = client.get("/evaluation")
    assert response.status_code == 200 and response.headers["content-security-policy"]
