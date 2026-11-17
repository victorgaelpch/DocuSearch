"""Pruebas del índice TF-IDF y del motor de búsqueda (DOC-08)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.app.config import Settings
from backend.app.documents.service import DocumentService
from backend.app.search.engine import SearchEngine, UnsupportedMethodError, make_snippet
from backend.app.search.lexical_corpus import TokenCache, build_lexical_corpus
from backend.app.search.ranking import top_k, validate_k
from backend.app.search.tfidf import TfidfIndex

DOCS = {
    "gatos.txt": "Los gatos domésticos son felinos pequeños. El gato caza ratones y duerme mucho.",
    "perros.txt": "Los perros son animales leales. El perro guardián protege la casa de los ladrones.",
    "python.txt": "Python es un lenguaje de programación interpretado. Los programas en Python son legibles.",
    "cocina.txt": "La receta de paella lleva arroz, azafrán y mariscos. Cocinar paella requiere paciencia.",
}


# -- índice -----------------------------------------------------------------------


def test_tfidf_ranks_by_cosine_similarity() -> None:
    docs = [["gato", "felino"], ["perro", "leal"], ["gato", "gato", "raton"]]
    index = TfidfIndex(docs, ["c0", "c1", "c2"])
    results = index.search(["gato"], 10)
    assert [i for i, _ in results] == [2, 0]
    assert results[0][1] >= results[1][1] > 0
    assert all(0 < s <= 1.0000001 for _, s in results)
    assert index.describe()["params"]["norm"] == "l2"


def test_tfidf_handles_empty_and_unknown_queries() -> None:
    index = TfidfIndex([["gato"], ["perro"]], ["a", "b"])
    assert index.search([], 10) == []
    assert index.search(["inexistente"], 10) == []
    empty = TfidfIndex([[], []], ["a", "b"])
    assert empty.search(["gato"], 10) == []
    assert TfidfIndex([], []).search(["gato"], 10) == []


def test_top_k_is_deterministic_on_ties_and_respects_k() -> None:
    scores = np.array([0.5, 0.9, 0.5, 0.0, 0.5])
    ids = ["c3", "c9", "c1", "c0", "c2"]
    assert top_k(scores, ids, 10) == [(1, 0.9), (2, 0.5), (4, 0.5), (0, 0.5)]
    assert top_k(scores, ids, 2) == [(1, 0.9), (2, 0.5)]
    assert top_k(np.zeros(3), ["a", "b", "c"], 5) == []


@pytest.mark.parametrize("bad", [0, -1, 101, 2.5, True, "10"])
def test_invalid_k(bad) -> None:
    with pytest.raises(ValueError):
        validate_k(bad)


def test_snippet_is_single_line_and_truncated() -> None:
    assert make_snippet("Hola\nmundo\n\nnuevo") == "Hola mundo nuevo"
    long = make_snippet("palabra " * 100)
    assert len(long) <= 301 and long.endswith("…")


# -- motor sobre el repositorio --------------------------------------------------


@pytest.fixture()
def service(tmp_path: Path) -> DocumentService:
    service = DocumentService(Settings.from_env(tmp_path / "data"))
    for name, text in DOCS.items():
        service.ingest(name, text.encode("utf-8"))
    return service


@pytest.fixture()
def engine(service: DocumentService, lexical_pipeline) -> SearchEngine:
    return SearchEngine(
        service.repository,
        pipeline=lexical_pipeline,
        cache_path=service.settings.paths.indexes_dir / "lexical_tokens.json",
    )


def test_engine_returns_hits_with_provenance(engine: SearchEngine) -> None:
    response = engine.search("lenguaje de programación", method="tfidf")
    assert response.hits, response
    top = response.hits[0]
    assert top.title == "python" and top.original_filename == "python.txt"
    assert top.rank == 1 and top.method.value == "tfidf"
    assert top.chunk_id.startswith(top.doc_id)
    assert "Python" in top.snippet
    assert response.k == 10 and response.collection == "user"
    assert [h.rank for h in response.hits] == list(range(1, len(response.hits) + 1))
    assert [h.score for h in response.hits] == sorted((h.score for h in response.hits), reverse=True)


def test_engine_query_without_accents_matches(engine: SearchEngine) -> None:
    assert engine.search("programacion", method="tfidf").hits[0].title == "python"


@pytest.mark.parametrize("query", ["", "   ", "el de la que", "¿?¡!", "xyzzy inexistente"])
def test_empty_or_unmatched_queries_do_not_fail(engine: SearchEngine, query: str) -> None:
    response = engine.search(query, method="tfidf")
    assert response.hits == []


def test_k_limits_results(engine: SearchEngine) -> None:
    assert len(engine.search("los animales gato perro", method="tfidf", k=1).hits) == 1
    with pytest.raises(ValueError):
        engine.search("gato", method="tfidf", k=0)


def test_unknown_method(engine: SearchEngine) -> None:
    with pytest.raises(UnsupportedMethodError):
        engine.search("gato", method="magia")


def test_results_are_reproducible_and_index_updates_after_upload(
    engine: SearchEngine, service: DocumentService
) -> None:
    first = engine.search("gato", method="tfidf")
    again = engine.search("gato", method="tfidf")
    assert [(h.chunk_id, h.score) for h in first.hits] == [(h.chunk_id, h.score) for h in again.hits]
    assert first.index_version == again.index_version

    service.ingest("felinos.txt", "El gato montés es un gato salvaje de Europa.".encode())
    updated = engine.search("gato", method="tfidf")
    assert updated.index_version != first.index_version
    assert "felinos.txt" in {h.original_filename for h in updated.hits}


def test_describe_records_parameters(engine: SearchEngine) -> None:
    info = engine.describe()
    assert info["chunks"] == 4
    assert info["lexical_pipeline"]["pipeline"] == "lexical"
    tfidf = info["indexes"][0]
    assert tfidf["method"] == "tfidf" and "scikit_learn" in tfidf["params"]


def test_token_cache_avoids_reprocessing(service: DocumentService, lexical_pipeline, monkeypatch) -> None:
    cache = service.settings.paths.indexes_dir / "tokens.json"
    first = build_lexical_corpus(service.repository, lexical_pipeline, "user", cache)
    assert cache.is_file()

    def fail(*args, **kwargs):
        raise AssertionError("no debería volver a tokenizar")

    monkeypatch.setattr(lexical_pipeline, "process_many", fail)
    second = build_lexical_corpus(service.repository, lexical_pipeline, "user", cache)
    assert second.tokens == first.tokens and second.version == first.version


def test_token_cache_invalidated_by_pipeline_config(tmp_path: Path, lexical_pipeline) -> None:
    path = tmp_path / "tokens.json"
    path.write_text('{"format": 1, "pipeline": "otro", "entries": {"x": {"h": "1", "t": ["a"]}}}')
    assert TokenCache(path, lexical_pipeline.config).entries == {}
    path.write_text("no es json")
    assert TokenCache(path, lexical_pipeline.config).entries == {}
