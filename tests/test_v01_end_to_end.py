"""Pruebas de extremo a extremo del MVP v0.1 (DOC-11).

Recorren el flujo completo con la API real (FastAPI TestClient) y archivos
sintéticos: carga → extracción → fragmentación 200/30 → indexación →
búsqueda → documento, página y original. No usan documentos privados.
"""

from __future__ import annotations

import io
import json
import random
import zipfile
from pathlib import Path

import docx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.app.cli import main as cli_main
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.search.evaluation import benchmark_latency
from backend.app.search.engine import SearchEngine

FIXTURES = Path(__file__).parent / "fixtures"
FILLER = (
    "La biblioteca municipal organiza talleres de lectura para estudiantes y vecinos "
    "durante todo el año con actividades culturales variadas"
).split()


def _filler(n: int, seed: int) -> str:
    rng = random.Random(seed)
    return " ".join(rng.choice(FILLER) for _ in range(n))


def _pdf(pages: list[str]) -> bytes:
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        words = text.split()
        lines = [" ".join(words[i : i + 10]) for i in range(0, len(words), 10)]
        page.insert_textbox(pymupdf.Rect(36, 36, 560, 806), "\n".join(lines), fontsize=7)
    data = document.tobytes()
    document.close()
    return data


def _docx(paragraphs: list[str]) -> bytes:
    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(tmp_path / "data")


@pytest.fixture()
def client(settings: Settings, lexical_pipeline) -> TestClient:
    return TestClient(create_app(settings))


def _upload(client: TestClient, name: str, data: bytes):
    return client.post("/documents", files={"file": (name, data)})


def test_full_flow_result_document_page_relation(client: TestClient) -> None:
    """Un término único en la página 3 se encuentra y se atribuye a esa página."""
    pages = [_filler(180, 1), _filler(180, 2), _filler(90, 3) + " xilófono " + _filler(90, 4)]
    upload = _upload(client, "informe_largo.pdf", _pdf(pages))
    assert upload.status_code == 201, upload.text
    body = upload.json()
    assert body["page_count"] == 3
    assert body["chunk_count"] == 4  # 540 palabras + 1 → ventanas de 200 con paso 170

    chunks = client.get(f"/documents/{body['doc_id']}/chunks").json()["items"]
    words = [c["text"].split() for c in chunks]
    assert [len(w) for w in words[:-1]] == [200, 200, 200]
    assert all(a[-30:] == b[:30] for a, b in zip(words, words[1:]))  # solapamiento 30

    results = client.get("/search", params={"q": "xilófono"}).json()["results"]
    assert results, "el término debe encontrarse"
    for hit in results:
        assert hit["doc_id"] == body["doc_id"]
        assert hit["page_start"] <= 3 <= hit["page_end"]
        chunk = next(c for c in chunks if c["chunk_id"] == hit["chunk_id"])
        assert "xilófono" in chunk["text"]
    download = client.get(results[0]["download_url"])
    assert download.status_code == 200 and download.content.startswith(b"%PDF")


def test_mixed_formats_search_spanish_k_and_no_results(client: TestClient) -> None:
    _upload(client, "fotosintesis.docx", _docx(["La fotosíntesis convierte la luz solar en energía química.", "Ocurre en los cloroplastos de las plantas."]))
    _upload(client, "volcanes.txt", "Los volcanes expulsan lava, ceniza y gases durante una erupción.".encode())
    _upload(client, "muestra.pdf", (FIXTURES / "muestra.pdf").read_bytes())

    top = client.get("/search", params={"q": "energía de la luz en plantas"}).json()["results"][0]
    assert top["original_filename"] == "fotosintesis.docx" and top["page"] is None
    assert client.get("/search", params={"q": "erupcion volcanica", "method": "tfidf"}).json()["results"][0]["original_filename"] == "volcanes.txt"

    k1 = client.get("/search", params={"q": "la", "k": 1}).json()
    assert k1["total"] == 0  # solo stopwords
    many = client.get("/search", params={"q": "lava luz índice", "k": 10}).json()
    assert 1 < many["total"] <= 10
    assert len(client.get("/search", params={"q": "lava luz índice", "k": 1}).json()["results"]) == 1
    assert client.get("/search", params={"q": "criptomoneda"}).json()["total"] == 0
    assert client.get("/search", params={"q": ""}).status_code == 422


def _invalid_payloads() -> list[tuple[str, bytes]]:
    rng = random.Random(42)
    valid = {name: (FIXTURES / name).read_bytes() for name in ("muestra.pdf", "muestra.docx", "muestra.txt")}
    payloads: list[tuple[str, bytes]] = []
    for name, data in valid.items():
        extension = Path(name).suffix
        for cut in (1, 5, 50, len(data) // 2, len(data) - 1):
            payloads.append((f"truncado_{cut}{extension}", data[:cut]))
        payloads.append((f"aleatorio{extension}", bytes(rng.randrange(256) for _ in range(2048))))
        corrupted = bytearray(data)
        for _ in range(40):
            corrupted[rng.randrange(len(corrupted))] = rng.randrange(256)
        payloads.append((f"corrupto{extension}", bytes(corrupted)))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<x/>")
        archive.writestr("word/document.xml", "<no es xml valido")
    payloads += [
        ("xml_roto.docx", buffer.getvalue()),
        ("vacio.pdf", b""),
        ("script.js", b"alert(1)"),
        ("sin_extension", b"hola"),
        ("../../escape.txt", b"texto"),
        ("CON.txt", b"texto"),
    ]
    return payloads


def test_no_invalid_file_breaks_the_service(client: TestClient) -> None:
    assert _upload(client, "muestra.txt", (FIXTURES / "muestra.txt").read_bytes()).status_code == 201
    statuses = []
    for name, data in _invalid_payloads():
        response = _upload(client, name, data)
        statuses.append((name, response.status_code))
        assert response.status_code < 500, (name, response.text)
        if response.status_code >= 400:
            assert response.json()["error"]["code"]
    assert any(code == 422 for _, code in statuses) and any(code == 415 for _, code in statuses)
    # el servicio sigue funcionando
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/search", params={"q": "embeddings"}).json()["total"] >= 1
    listed = client.get("/documents").json()
    for item in listed["items"]:
        assert client.get(f"/documents/{item['doc_id']}/download").status_code == 200


def test_metadata_and_index_survive_restart(settings: Settings, lexical_pipeline) -> None:
    first = TestClient(create_app(settings))
    doc_id = _upload(first, "muestra.docx", (FIXTURES / "muestra.docx").read_bytes()).json()["doc_id"]
    before = first.get("/search", params={"q": "lematización"}).json()

    restarted = TestClient(create_app(settings))
    detail = restarted.get(f"/documents/{doc_id}").json()
    assert detail["extraction_status"] == "extracted" and detail["metadata"]["chunking"]["chunk_size"] == 200
    after = restarted.get("/search", params={"q": "lematización"}).json()
    assert after["index_version"] == before["index_version"]
    assert [r["chunk_id"] for r in after["results"]] == [r["chunk_id"] for r in before["results"]]


def test_latency_under_two_seconds_on_synthetic_corpus(client: TestClient, settings: Settings) -> None:
    """RNF de tiempo de respuesta sobre ~150 fragmentos sintéticos (no sustituye a la medición real)."""
    for i in range(30):
        _upload(client, f"doc_{i}.txt", (_filler(900, 100 + i) + f" termino{i}").encode())
    assert client.get("/search", params={"q": "biblioteca"}).status_code == 200
    engine: SearchEngine = client.app.state.search_engine
    report = benchmark_latency(
        engine, ["talleres de lectura", "termino7", "biblioteca municipal"], collection="user", repeats=3
    )
    assert all(m["under_2s"] for m in report["methods"].values()), report


def test_cli_corpus_stats_import_and_evaluate(settings: Settings, monkeypatch, capsys, lexical_pipeline) -> None:
    """Comandos del corpus y de evaluación con un manifiesto sintético mínimo."""
    from backend.app import cli
    from backend.app.corpus.wikipedia import text_sha256

    corpus_dir = settings.paths.root.parent / "corpus_cfg"
    texts_dir = settings.paths.root / "corpus" / "wikipedia_es"
    corpus_dir.mkdir(parents=True)
    texts_dir.mkdir(parents=True)
    articles = []
    for pageid, (title, text) in enumerate(
        {"Oro": "El oro es un metal precioso amarillo. " * 10, "Lisosoma": "El lisosoma digiere residuos celulares. " * 10}.items(), start=1
    ):
        (texts_dir / f"{pageid}.txt").write_text(text, encoding="utf-8")
        articles.append({"title": title, "pageid": pageid, "revid": pageid, "topic": "t", "words": 60,
                         "sha256": text_sha256(text), "url": f"https://es.wikipedia.org/w/index.php?oldid={pageid}"})
    (corpus_dir / "manifest.json").write_text(json.dumps({"articles": articles, "stats": {"articles": 2}}), encoding="utf-8")
    queries = corpus_dir / "queries.json"
    queries.write_text(json.dumps({"name": "mini", "queries": [
        {"id": "q1", "type": "lexical", "query": "metal amarillo", "relevant": ["Oro"]},
        {"id": "q2", "type": "paraphrase", "query": "orgánulo que digiere residuos", "relevant": ["Lisosoma"]},
    ]}), encoding="utf-8")

    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(settings.paths.root))
    monkeypatch.setattr(cli, "CORPUS_DIR", corpus_dir)
    assert cli_main(["corpus", "stats"]) == 0
    assert cli_main(["corpus", "import"]) == 0
    assert '"imported": 2' in capsys.readouterr().out
    output = settings.paths.root / "eval.json"
    assert cli_main(["evaluate", "--queries", str(queries), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["bm25"]["all"]["mrr@10"] == 1.0
    assert cli_main(["benchmark", "--queries", str(queries), "--repeats", "1"]) == 0
