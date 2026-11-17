"""Pruebas de BM25 y de la evaluación con consultas anotadas (DOC-09)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.documents.models import WIKIPEDIA_COLLECTION
from backend.app.documents.service import DocumentService
from backend.app.search.bm25 import BM25Index
from backend.app.search.engine import SearchEngine
from backend.app.search.evaluation import (
    AnnotatedQuery,
    document_ranking,
    evaluate,
    format_table,
    load_queries,
    ndcg_at,
    reciprocal_rank,
    recall_at,
)

REPO = Path(__file__).resolve().parents[1]


# -- BM25 ---------------------------------------------------------------------------


def test_bm25_score_matches_formula() -> None:
    docs = [["gato", "gato", "perro"], ["perro"], ["raton", "queso", "gato", "casa"]]
    index = BM25Index(docs, ["a", "b", "c"], k1=1.2, b=0.75)
    n, avgdl = 3, (3 + 1 + 4) / 3
    idf = math.log(1 + (n - 2 + 0.5) / (2 + 0.5))  # "gato" aparece en 2 fragmentos
    expected = idf * 2 * 2.2 / (2 + 1.2 * (1 - 0.75 + 0.75 * 3 / avgdl))
    assert index.scores(["gato"])[0] == pytest.approx(expected)
    assert index.scores(["gato"])[1] == 0


def test_bm25_rare_terms_weigh_more_and_idf_is_non_negative() -> None:
    docs = [["comun", "raro"], ["comun"], ["comun"], ["comun"]]
    index = BM25Index(docs, ["a", "b", "c", "d"])
    assert index.idf["raro"] > index.idf["comun"] >= 0
    assert [i for i, _ in index.search(["comun", "raro"], 10)][0] == 0


def test_bm25_term_frequency_saturates_and_length_normalizes() -> None:
    index = BM25Index([["x"] * 1, ["x"] * 10, ["x"] + ["y"] * 50], ["a", "b", "c"])
    s = index.scores(["x"])
    assert s[1] > s[0]  # más frecuencia, más puntuación…
    assert s[1] < 10 * s[0]  # …pero saturada por k1
    assert s[2] < s[0]  # documento largo penalizado por b


def test_bm25_without_length_normalization() -> None:
    index = BM25Index([["x"], ["x"] + ["y"] * 50], ["a", "b"], b=0)
    s = index.scores(["x"])
    assert s[0] == pytest.approx(s[1])


def test_bm25_query_terms_counted_once_and_unknown_terms() -> None:
    index = BM25Index([["gato"], ["perro"]], ["a", "b"])
    assert index.scores(["gato", "gato"]).tolist() == index.scores(["gato"]).tolist()
    assert index.search(["inexistente"], 10) == []
    assert index.search([], 10) == []
    assert BM25Index([], []).search(["gato"], 5) == []
    assert BM25Index([[], []], ["a", "b"]).search(["gato"], 5) == []


@pytest.mark.parametrize(("k1", "b"), [(-0.1, 0.5), (1.2, 1.5), (1.2, -0.1)])
def test_bm25_invalid_parameters(k1: float, b: float) -> None:
    with pytest.raises(ValueError):
        BM25Index([["a"]], ["a"], k1=k1, b=b)


def test_bm25_describe_documents_parameters() -> None:
    info = BM25Index([["a", "b"]], ["x"]).describe()
    assert info["params"]["k1"] == 1.5 and info["params"]["b"] == 0.75
    assert "ln(1 +" in info["params"]["idf"]


# -- motor: BM25 por defecto y comparación con TF-IDF ---------------------------------

TEXTS = {
    "gatos.txt": "Los gatos son felinos domésticos. El gato caza ratones por la noche.",
    "perros.txt": "Los perros son animales leales que protegen la casa.",
    "felinos.txt": "Los grandes felinos como el león y el tigre son depredadores.",
    "python.txt": "Python es un lenguaje de programación muy usado en ciencia de datos.",
}


@pytest.fixture()
def engine(tmp_path: Path, lexical_pipeline) -> SearchEngine:
    service = DocumentService(Settings.from_env(tmp_path / "data"))
    for name, text in TEXTS.items():
        service.ingest(name, text.encode("utf-8"))
    for title, text in {"León": "El león es un felino de África.", "Java": "Java es un lenguaje."}.items():
        service.ingest_corpus_text(
            collection=WIKIPEDIA_COLLECTION, title=title, text=text, filename=f"{title}.txt"
        )
    return SearchEngine(service.repository, pipeline=lexical_pipeline)


def test_bm25_is_default_and_reproducible(engine: SearchEngine) -> None:
    first = engine.search("felino depredador")
    assert first.method.value == "bm25"
    assert first.hits[0].original_filename == "felinos.txt"
    second = engine.search("felino depredador")
    assert [(h.chunk_id, h.score, h.rank) for h in first.hits] == [
        (h.chunk_id, h.score, h.rank) for h in second.hits
    ]


def test_bm25_and_tfidf_share_corpus_and_metadata(engine: SearchEngine) -> None:
    bm25 = engine.search("gato felino", method="bm25")
    tfidf = engine.search("gato felino", method="tfidf")
    assert bm25.index_version == tfidf.index_version  # mismo corpus
    assert {h.doc_id for h in bm25.hits} == {h.doc_id for h in tfidf.hits}
    for hit in bm25.hits:
        document = engine.repository.get_document(hit.doc_id)
        assert hit.title == document.title and document.storage_path  # original recuperable


def test_collections_are_searched_separately(engine: SearchEngine) -> None:
    user = engine.search("lenguaje", collection="user")
    wiki = engine.search("lenguaje", collection=WIKIPEDIA_COLLECTION)
    assert {h.original_filename for h in user.hits} == {"python.txt"}
    assert {h.title for h in wiki.hits} == {"Java"}


# -- métricas -------------------------------------------------------------------------


def test_metrics_known_values() -> None:
    ranking = ["d3", "d1", "d7", "d2"]
    relevant = {"d1", "d2"}
    assert recall_at(ranking, relevant, 1) == 0
    assert recall_at(ranking, relevant, 2) == 0.5
    assert recall_at(ranking, relevant, 10) == 1
    assert reciprocal_rank(ranking, relevant) == 0.5
    expected = (1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3))
    assert ndcg_at(ranking, relevant) == pytest.approx(expected)
    assert ndcg_at(["d1", "d2"], relevant) == pytest.approx(1.0)
    assert reciprocal_rank(["x"] * 10 + ["d1"], relevant) == 0  # fuera del top-10
    assert recall_at([], set(), 5) == 0


def test_document_ranking_deduplicates_chunks() -> None:
    assert document_ranking(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_evaluate_on_small_collection(engine: SearchEngine) -> None:
    queries = [
        AnnotatedQuery("q1", "león", "lexical", ("León",)),
        AnnotatedQuery("q2", "lenguaje", "lexical", ("Java",)),
    ]
    report = evaluate(engine, queries, collection=WIKIPEDIA_COLLECTION)
    assert report["summary"]["bm25"]["all"]["mrr@10"] == 1.0
    assert report["summary"]["tfidf"]["all"]["recall@1"] == 1.0
    assert len(report["per_query"]) == 4
    assert "| bm25 | 2 | all |" in format_table(report)


def test_evaluate_rejects_unknown_relevant_titles(engine: SearchEngine) -> None:
    with pytest.raises(ValueError, match="inexistentes"):
        evaluate(engine, [AnnotatedQuery("q", "x", "lexical", ("No existe",))], collection=WIKIPEDIA_COLLECTION)


def test_versioned_query_set_is_valid_against_manifest() -> None:
    queries, meta = load_queries(REPO / "evaluation" / "queries_wikipedia_es.json")
    manifest = json.loads((REPO / "corpus" / "wikipedia_es" / "manifest.json").read_text(encoding="utf-8"))
    titles = {a["title"] for a in manifest["articles"]}
    assert all(t in titles for q in queries for t in q.relevant_titles)
    kinds = {q.kind for q in queries}
    assert kinds == {"lexical", "paraphrase"}
    assert sum(q.kind == "paraphrase" for q in queries) >= 10
    assert "ANTES" in meta["methodology"]
