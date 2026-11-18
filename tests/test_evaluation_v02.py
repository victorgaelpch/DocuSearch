"""Evaluación v0.2: subconjuntos dev/test, significación y CLI (DOC-16)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.search.evaluation import compare_methods, load_queries, paired_permutation_test

REPO = Path(__file__).resolve().parents[1]
QUERIES_V2 = REPO / "evaluation" / "queries_wikipedia_es_v2.json"


def test_v2_query_file_is_well_formed_and_disjoint_from_v1() -> None:
    queries, meta = load_queries(QUERIES_V2)
    assert len(queries) == 48 and "revisión humana" in meta["annotator"]
    assert {q.split for q in queries} == {"dev", "test"}
    dev, _ = load_queries(QUERIES_V2, split="dev")
    test, _ = load_queries(QUERIES_V2, split="test")
    assert (len(dev), len(test)) == (16, 32)
    assert {q.kind for q in test} == {"lexical", "paraphrase"}
    v1, _ = load_queries(REPO / "evaluation" / "queries_wikipedia_es.json")
    v1_relevant = {t for q in v1 for t in q.relevant_titles}
    assert not v1_relevant & {t for q in queries for t in q.relevant_titles}
    manifest = json.loads((REPO / "corpus" / "wikipedia_es" / "manifest.json").read_text(encoding="utf-8"))
    titles = {a["title"] for a in manifest["articles"]}
    assert all(t in titles for q in queries for t in q.relevant_titles)


def test_load_queries_split_defaults_and_errors(tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    path.write_text(json.dumps({"queries": [{"id": "a", "query": "x", "relevant": ["X"]}]}), encoding="utf-8")
    queries, _ = load_queries(path)
    assert queries[0].split == "test"
    with pytest.raises(ValueError):
        load_queries(path, split="dev")


def test_permutation_test_exact_and_sampled() -> None:
    assert paired_permutation_test([1, 1, 1], [1, 1, 1]) == 1.0
    assert paired_permutation_test([], []) == 1.0
    # 5 diferencias iguales: solo "todo +" y "todo -" son tan extremas → 2/32
    assert paired_permutation_test([1] * 5, [0] * 5) == pytest.approx(2 / 32)
    assert paired_permutation_test([1, 0], [0, 1]) == 1.0
    many_a, many_b = [1.0] * 20, [0.0] * 20
    p = paired_permutation_test(many_a, many_b, samples=2000, seed=1)
    assert p < 0.01 and p == paired_permutation_test(many_a, many_b, samples=2000, seed=1)
    with pytest.raises(ValueError):
        paired_permutation_test([1], [1, 2])


def test_compare_methods_counts_wins_and_losses() -> None:
    rows = []
    for qid, (base, other) in {"q1": (1.0, 0.5), "q2": (0.5, 1.0), "q3": (0.0, 1.0)}.items():
        rows += [
            {"id": qid, "method": "bm25", "mrr@10": base, "ndcg@10": base},
            {"id": qid, "method": "semantic", "mrr@10": other, "ndcg@10": other},
        ]
    result = compare_methods({"per_query": rows}, "bm25")
    values = result["comparisons"]["semantic"]["mrr@10"]
    assert (values["wins"], values["losses"]) == (2, 1)
    assert values["mean_difference"] == pytest.approx(1 / 3, abs=1e-4)
    assert 0 < values["p_value"] <= 1
    with pytest.raises(ValueError):
        compare_methods({"per_query": rows}, "tfidf")


def test_cli_evaluate_with_split_methods_and_significance(tmp_path: Path, monkeypatch, capsys, lexical_pipeline) -> None:
    pytest.importorskip("faiss")
    from backend.app import cli
    from backend.app.cli import main as cli_main
    from backend.app.config import Settings
    from backend.app.documents.service import DocumentService
    from backend.app.nlp import embeddings
    from backend.app.nlp.embeddings import HashingEncoder

    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(tmp_path / "data"))
    service = DocumentService(Settings.from_env())
    texts = {"Oro": "El oro es un metal precioso amarillo. " * 5, "Lisosoma": "El lisosoma digiere residuos celulares. " * 5}
    for title, text in texts.items():
        service.ingest_corpus_text(collection="wikipedia_es", title=title, text=text, filename=f"{title}.txt")
    queries = tmp_path / "queries.json"
    queries.write_text(json.dumps({"name": "mini", "queries": [
        {"id": "d1", "split": "dev", "type": "lexical", "query": "metal amarillo", "relevant": ["Oro"]},
        {"id": "t1", "split": "test", "type": "lexical", "query": "metal precioso", "relevant": ["Oro"]},
        {"id": "t2", "split": "test", "type": "paraphrase", "query": "orgánulo que digiere residuos", "relevant": ["Lisosoma"]},
    ]}), encoding="utf-8")
    monkeypatch.setattr(embeddings, "get_encoder", lambda: HashingEncoder(64))
    output = tmp_path / "eval.json"
    assert cli_main(["evaluate", "--queries", str(queries), "--split", "test",
                     "--methods", "bm25", "semantic", "hybrid", "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["split"] == "test" and {r["id"] for r in report["per_query"]} == {"t1", "t2"}
    assert set(report["significance"]["comparisons"]) == {"semantic", "hybrid"}
    assert "p=" in capsys.readouterr().out

    # el experimento de textos largos usa otro codificador y un índice aparte
    created = []

    class FakeST(HashingEncoder):
        def __init__(self, config):
            super().__init__(64)
            created.append(config.long_text)

    monkeypatch.setattr(embeddings, "SentenceTransformerEncoder", FakeST)
    engine = cli._search_engine(Settings.from_env(), long_text="truncate")
    assert engine.indexes_dir.name == "experiment-truncate"
    engine.semantic.index("wikipedia_es")
    assert created == ["truncate"]
