"""Búsqueda híbrida BM25 + semántica con Reciprocal Rank Fusion (DOC-15)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.search.hybrid import RRF_K, reciprocal_rank_fusion


# --- RRF ---------------------------------------------------------------------


def test_rrf_formula_and_order() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "d"]], k=60)
    scores = dict(fused)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["d"] == pytest.approx(1 / 63)
    assert [item for item, _ in fused] == ["b", "c", "a", "d"]


def test_rrf_document_in_one_list_only_still_counts() -> None:
    fused = dict(reciprocal_rank_fusion([["solo_lexico"], []]))
    assert fused == {"solo_lexico": pytest.approx(1 / (RRF_K + 1))}


def test_rrf_ties_broken_by_id_and_limit() -> None:
    fused = reciprocal_rank_fusion([["z", "y"], ["y", "z"]], k=60)
    assert [item for item, _ in fused] == ["y", "z"]  # misma puntuación → orden por id
    assert reciprocal_rank_fusion([["a", "b", "c"]], limit=2) == reciprocal_rank_fusion([["a", "b", "c"]])[:2]


def test_rrf_edge_cases() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []
    # repetido: cuenta solo en su mejor posición; las demás conservan la suya
    assert dict(reciprocal_rank_fusion([["a", "a", "b"]], k=0)) == {"a": 1.0, "b": pytest.approx(1 / 3)}
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], k=-1)


# --- motor y API -------------------------------------------------------------

faiss = pytest.importorskip("faiss")

from backend.app.config import Settings  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.nlp.embeddings import EmbeddingUnavailableError, HashingEncoder  # noqa: E402
from tests.auth_helpers import admin_client

DOCS = {
    "volcanes.txt": "Los volcanes expulsan lava ceniza y gases durante una erupción violenta.",
    "fotosintesis.txt": "La fotosíntesis convierte luz solar en energía química dentro de las plantas.",
    "cafe.txt": "El café se cultiva en montañas tropicales y se tuesta antes de molerlo.",
}


def _client(tmp_path: Path, factory=lambda: HashingEncoder(64)) -> TestClient:
    client = admin_client(Settings.from_env(tmp_path / "data"), encoder_factory=factory)
    for name, text in DOCS.items():
        assert client.post("/documents", files={"file": (name, text.encode())}).status_code == 201
    return client


def test_hybrid_fuses_bm25_and_semantic(tmp_path: Path, lexical_pipeline) -> None:
    client = _client(tmp_path)
    params = {"q": "lava de volcanes", "k": 10}
    bm25 = client.get("/search", params=params).json()
    semantic = client.get("/search", params={**params, "method": "semantic"}).json()
    hybrid = client.get("/search", params={**params, "method": "hybrid"}).json()
    assert set(hybrid) == set(bm25) and hybrid["method"] == "hybrid"
    expected = reciprocal_rank_fusion(
        [[r["chunk_id"] for r in bm25["results"]], [r["chunk_id"] for r in semantic["results"]]], limit=10
    )
    assert [(r["chunk_id"], r["score"]) for r in hybrid["results"]] == [(c, round(s, 6)) for c, s in expected]
    assert hybrid["results"][0]["original_filename"] == "volcanes.txt"
    assert hybrid["query_tokens"] == bm25["query_tokens"]
    assert hybrid["index_version"] not in (bm25["index_version"], semantic["index_version"])


def test_hybrid_keeps_results_found_by_only_one_method(tmp_path: Path, lexical_pipeline) -> None:
    client = _client(tmp_path)
    # "la" es stopword: BM25 no devuelve nada y la híbrida equivale a la semántica
    semantic = client.get("/search", params={"q": "la", "method": "semantic"}).json()
    hybrid = client.get("/search", params={"q": "la", "method": "hybrid"}).json()
    assert client.get("/search", params={"q": "la"}).json()["total"] == 0
    assert [r["chunk_id"] for r in hybrid["results"]] == [r["chunk_id"] for r in semantic["results"]]


def test_hybrid_k_determinism_and_index_info(tmp_path: Path, lexical_pipeline) -> None:
    client = _client(tmp_path)
    params = {"q": "energía solar y café", "method": "hybrid"}
    assert len(client.get("/search", params={**params, "k": 1}).json()["results"]) == 1
    first = client.get("/search", params=params).json()
    assert first == {**client.get("/search", params=params).json(), "took_ms": first["took_ms"]}
    info = {i["method"]: i for i in client.get("/search/index").json()["indexes"]}
    assert info["hybrid"]["params"] == {"k": 60, "candidates": 100}


def test_hybrid_without_semantic_extra_returns_503(tmp_path: Path, lexical_pipeline) -> None:
    def missing():
        raise EmbeddingUnavailableError("Falta el extra 'semantic'")

    client = _client(tmp_path, factory=missing)
    response = client.get("/search", params={"q": "volcanes", "method": "hybrid"})
    assert response.status_code == 503 and response.json()["error"]["code"] == "semantic_unavailable"
