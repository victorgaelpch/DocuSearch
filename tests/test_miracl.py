"""Importación de MIRACL español para evaluación (DOC-16). Sin red: descarga simulada."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.corpus import miracl
from backend.app.documents.service import DocumentService

ROWS = [
    {
        "query_id": "1",
        "query": "¿Qué es el dengue?",
        "positive_passages": [{"docid": "10#0", "title": "Dengue", "text": "El dengue es una enfermedad viral transmitida por mosquitos."}],
        "negative_passages": [{"docid": "20#3", "title": "Malaria", "text": "La malaria la causa un parásito."}],
    },
    {
        "query_id": "2",
        "query": "¿Dónde se cultiva el café?",
        "positive_passages": [
            {"docid": "30#1", "title": "Café", "text": "El café se cultiva en regiones tropicales de montaña."},
            {"docid": "10#0", "title": "Dengue", "text": "El dengue es una enfermedad viral transmitida por mosquitos."},
        ],
        "negative_passages": [{"docid": "40#0", "title": "Vacío", "text": "   "}],
    },
    {"query_id": "3", "query": "sin relevantes", "positive_passages": [], "negative_passages": []},
]


def test_parse_rows_deduplicates_passages_and_drops_queries_without_positives() -> None:
    queries, passages = miracl.parse_rows(ROWS)
    assert [q.qid for q in queries] == ["1", "2"]
    assert set(passages) == {"10#0", "20#3", "30#1"}  # sin repetidos ni pasajes vacíos
    assert queries[1].positives == ("30#1", "10#0") and queries[1].negatives == ()
    passage = passages["10#0"]
    assert passage.unique_title == "Dengue [10#0]"
    assert passage.indexed_text.startswith("Dengue\nEl dengue")


def test_queries_payload_matches_evaluation_format(tmp_path: Path) -> None:
    from backend.app.search.evaluation import load_queries

    queries, passages = miracl.parse_rows(ROWS)
    path = tmp_path / "q.json"
    miracl.write_queries(path, miracl.queries_file_payload(queries, passages))
    loaded, meta = load_queries(path)
    assert [q.relevant_titles for q in loaded] == [("Dengue [10#0]",), ("Café [30#1]", "Dengue [10#0]")]
    assert meta["annotator"] == "humano (MIRACL)" and meta["source"]["sha256"] == miracl.PARQUET_SHA256


def test_import_is_idempotent_and_separate_collection(tmp_path: Path) -> None:
    service = DocumentService(Settings.from_env(tmp_path / "data"))
    queries, passages = miracl.parse_rows(ROWS)
    assert miracl.import_miracl(service, queries, passages) == {"queries": 2, "passages": 3, "imported": 3, "already_present": 0}
    assert miracl.import_miracl(service, queries, passages)["already_present"] == 3
    assert service.repository.count_documents(miracl.MIRACL_COLLECTION) == 3
    assert service.repository.count_documents("user") == 0
    document = service.repository.list_documents(miracl.MIRACL_COLLECTION, limit=10, offset=0)[0]
    assert document.source_uri.startswith("miracl:es:") and document.extra["miracl_docid"]


def test_ensure_parquet_verifies_hash(tmp_path: Path, monkeypatch) -> None:
    payload = b"parquet falso"
    monkeypatch.setattr(miracl, "PARQUET_SHA256", hashlib.sha256(payload).hexdigest())
    calls = []
    monkeypatch.setattr(miracl, "_download", lambda url: calls.append(url) or payload)
    target = tmp_path / "m" / "dev.parquet"
    assert miracl.ensure_parquet(target).read_bytes() == payload
    miracl.ensure_parquet(target)
    assert len(calls) == 1 and miracl.PARQUET_REVISION in calls[0]

    monkeypatch.setattr(miracl, "_download", lambda url: b"otro")
    target.write_bytes(b"corrupto")
    with pytest.raises(miracl.MiraclError, match="SHA-256"):
        miracl.ensure_parquet(target)

    def offline(url):
        raise OSError("sin red")

    monkeypatch.setattr(miracl, "_download", offline)
    with pytest.raises(miracl.MiraclError, match="sin red"):
        miracl.ensure_parquet(target)


def test_read_parquet_roundtrip(tmp_path: Path) -> None:
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    path = tmp_path / "x.parquet"
    pq.write_table(pa.Table.from_pylist(ROWS[:2]), path)
    queries, passages = miracl.parse_rows(miracl.read_parquet(path))
    assert len(queries) == 2 and len(passages) == 3


def test_cli_miracl(tmp_path: Path, monkeypatch, capsys) -> None:
    from backend.app.cli import main as cli_main

    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(miracl, "ensure_parquet", lambda path: path)
    monkeypatch.setattr(miracl, "read_parquet", lambda path: ROWS)
    assert cli_main(["miracl"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["imported"] == 3 and Path(report["queries_file"]).is_file()

    def broken(path):
        raise miracl.MiraclError("falta pyarrow")

    monkeypatch.setattr(miracl, "read_parquet", broken)
    assert cli_main(["miracl"]) == 1
