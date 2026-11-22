"""Pruebas del corpus de Wikipedia sin acceso a red (DOC-05)."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.corpus import wikipedia
from backend.app.corpus.wikipedia import (
    ReconstructionError,
    WikipediaClient,
    WikipediaError,
    build,
    freeze,
    iter_corpus_texts,
    text_sha256,
    wikitext_to_text,
)
from backend.app.documents import WIKIPEDIA_COLLECTION, DuplicateDocumentError
from backend.app.documents.service import DocumentService
from backend.app.main import create_app
from tests.auth_helpers import admin_client

LONG = " ".join(["palabra"] * 60)


def _article(title: str, body: str) -> str:
    return (
        "{{Ficha|nombre=" + title + "}}\n"
        f"'''{title}''' es un [[tema|tema importante]]. {body}<ref>Cita</ref>\n"
        "[[Archivo:Foto.jpg|miniaturadeimagen|Pie]]\n"
        "== Historia ==\nTexto histórico relevante.\n"
        "{| class=\"wikitable\"\n| a || b\n|}\n"
        "== Referencias ==\n{{listaref}}\n[[Categoría:Pruebas]]"
    )


PAGES: dict[int, dict[str, Any]] = {
    1: {"title": "Oro", "revid": 101, "wikitext": _article("Oro", "Metal precioso. " + LONG)},
    2: {"title": "Plata", "revid": 102, "wikitext": _article("Plata", "Metal blanco. " + LONG)},
    3: {"title": "Corto", "revid": 103, "wikitext": "'''Corto''' es breve."},
    4: {"title": "Redirección", "revid": 104, "wikitext": "#REDIRECCIÓN [[Oro]]"},
    5: {"title": "Copia de Oro", "revid": 105, "wikitext": _article("Oro", "Metal precioso. " + LONG)},
    6: {"title": "Vacío", "revid": 106, "wikitext": "{{Plantilla}}\n[[Categoría:Nada]]"},
    7: {"title": "Cobre", "revid": 107, "wikitext": _article("Cobre", "Conductor. " + LONG)},
}
CATEGORIES = {"Metales": [1, 2, 3, 4, 5, 6], "Conductores": [7, 1]}


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(params)
        if params.get("list") == "categorymembers":
            name = params["cmtitle"].split(":", 1)[1]
            members = [{"pageid": p, "title": PAGES[p]["title"], "ns": 0} for p in CATEGORIES[name]]
            return {"query": {"categorymembers": members}}
        if "pageids" in params:
            ids = [int(i) for i in params["pageids"].split("|")]
        else:
            revids = {int(i) for i in params["revids"].split("|")}
            ids = [p for p, page in PAGES.items() if page["revid"] in revids]
        pages = [
            {
                "pageid": p,
                "title": PAGES[p]["title"],
                "revisions": [
                    {
                        "revid": PAGES[p]["revid"],
                        "timestamp": "2026-01-01T00:00:00Z",
                        "slots": {"main": {"content": PAGES[p]["wikitext"]}},
                    }
                ],
            }
            for p in ids
        ]
        return {"query": {"pages": pages}}


@pytest.fixture()
def topics(tmp_path: Path) -> Path:
    path = tmp_path / "topics.json"
    path.write_text(
        json.dumps(
            {
                "articles_per_topic": 10,
                "topics": [
                    {"topic": "metales", "categories": ["Metales"]},
                    {"topic": "electricidad", "categories": ["Conductores"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _client(api: FakeApi | None = None) -> WikipediaClient:
    return WikipediaClient(getter=api or FakeApi(), sleep=lambda s: None)


def test_wikitext_conversion_removes_noise_and_tail_sections() -> None:
    text = wikitext_to_text(_article("Oro", "Metal precioso."))
    assert text.startswith("Oro es un tema importante. Metal precioso.")
    assert "Historia" in text and "Texto histórico relevante." in text
    for noise in ("Ficha", "Cita", "Foto.jpg", "wikitable", "listaref", "Categoría", "Referencias"):
        assert noise not in text


def test_freeze_filters_and_records_provenance(tmp_path: Path, topics: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    texts = tmp_path / "texts"
    manifest = freeze(_client(), topics, manifest_path, texts, log=lambda m: None)

    titles = [a["title"] for a in manifest["articles"]]
    assert titles == ["Oro", "Plata", "Cobre"]
    reasons = {e.get("title", e.get("pageid")): e["reason"] for e in manifest["excluded"]}
    assert reasons["Corto"] == "short<50"
    assert reasons["Redirección"] == "redirect"
    assert reasons["Copia de Oro"] == "duplicate_text"
    assert reasons["Vacío"] == "empty"
    assert reasons["Oro"] == "duplicate_page"  # repetido en la segunda categoría

    oro = manifest["articles"][0]
    assert oro["revid"] == 101 and oro["topic"] == "metales"
    assert oro["url"] == "https://es.wikipedia.org/w/index.php?oldid=101"
    assert oro["words"] >= 50
    assert manifest["license"] == "CC BY-SA 4.0"
    assert manifest["converter"]["version"] == wikipedia.CONVERTER_VERSION
    assert manifest["stats"]["articles"] == 3
    assert manifest["stats"]["by_topic"] == {"electricidad": 1, "metales": 2}
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == manifest
    assert (texts / "1.txt").read_text(encoding="utf-8")


def test_build_reconstructs_exact_texts_from_revisions(tmp_path: Path, topics: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    freeze(_client(), topics, manifest_path, tmp_path / "a", log=lambda m: None)
    api = FakeApi()
    report = build(_client(api), manifest_path, tmp_path / "b", log=lambda m: None)
    assert report["written"] == 3 and report["hash_mismatch"] == []
    assert all("revids" in c for c in api.calls)  # usa revisiones fijadas, no la versión actual
    for name in ("1.txt", "2.txt", "7.txt"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_build_detects_changed_content(tmp_path: Path, topics: Path, monkeypatch) -> None:
    manifest_path = tmp_path / "manifest.json"
    freeze(_client(), topics, manifest_path, tmp_path / "a", log=lambda m: None)
    monkeypatch.setitem(PAGES[2], "wikitext", _article("Plata", "Texto distinto. " + LONG))
    with pytest.raises(ReconstructionError):
        build(_client(), manifest_path, tmp_path / "b", log=lambda m: None)


def test_iter_corpus_texts_checks_hashes(tmp_path: Path, topics: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    texts = tmp_path / "texts"
    freeze(_client(), topics, manifest_path, texts, log=lambda m: None)
    pairs = list(iter_corpus_texts(manifest_path, texts))
    assert len(pairs) == 3 and all(text_sha256(t) == a["sha256"] for a, t in pairs)
    (texts / "1.txt").write_text("alterado", encoding="utf-8")
    with pytest.raises(ReconstructionError):
        list(iter_corpus_texts(manifest_path, texts))
    (texts / "1.txt").unlink()
    with pytest.raises(FileNotFoundError):
        list(iter_corpus_texts(manifest_path, texts))


def test_corpus_documents_stay_separate_from_user_uploads(tmp_path: Path) -> None:
    settings = Settings.from_env(tmp_path / "data")
    service = DocumentService(settings)
    text = "Texto del corpus experimental. " + LONG
    corpus = service.ingest_corpus_text(
        collection=WIKIPEDIA_COLLECTION,
        title="Oro",
        text=text,
        filename="1.txt",
        source_uri="https://es.wikipedia.org/w/index.php?oldid=101",
        metadata={"topic": "metales", "revid": 101},
    )
    user = service.ingest("mio.txt", text.encode("utf-8"))  # mismo contenido, otra colección

    assert corpus.document.doc_id != user.document.doc_id
    assert corpus.document.collection == "wikipedia_es"
    assert corpus.document.source_type.value == "corpus"
    assert corpus.document.storage_path.startswith("wikipedia_es/")
    assert corpus.document.extra["topic"] == "metales"
    assert corpus.chunks and corpus.chunks[0].doc_id == corpus.document.doc_id

    client = admin_client(settings)
    listed = client.get("/documents").json()
    assert [d["doc_id"] for d in listed["items"]] == [user.document.doc_id]

    with pytest.raises(DuplicateDocumentError):
        service.ingest_corpus_text(
            collection=WIKIPEDIA_COLLECTION, title="Oro", text=text, filename="1.txt"
        )
    with pytest.raises(ValueError):
        service.ingest_corpus_text(collection="user", title="x", text=text, filename="x.txt")


def test_client_retries_on_429_and_raises_on_404(monkeypatch) -> None:
    responses = [
        urllib.error.HTTPError("u", 429, "Too Many", {"Retry-After": "3"}, None),
        io.BytesIO(b'{"query": {"categorymembers": []}}'),
    ]
    sleeps: list[float] = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout):
        assert "User-Agent" in request.headers or "User-agent" in request.headers
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return Response(item.getvalue())

    monkeypatch.setattr(wikipedia.urllib.request, "urlopen", fake_urlopen)
    client = WikipediaClient(sleep=sleeps.append, min_interval=0)
    assert client.category_members("X", 5) == []
    assert 3.0 in sleeps

    def not_found(request, timeout):
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    monkeypatch.setattr(wikipedia.urllib.request, "urlopen", not_found)
    with pytest.raises(WikipediaError):
        client.category_members("X", 5)


def test_api_error_payload_raises() -> None:
    client = WikipediaClient(getter=lambda p: {"error": {"info": "bad"}}, sleep=lambda s: None)
    with pytest.raises(WikipediaError, match="bad"):
        client.category_members("X", 1)


def test_versioned_manifest_is_consistent() -> None:
    """El manifiesto versionado del repositorio cumple los filtros documentados."""
    path = Path(__file__).resolve().parents[1] / "corpus" / "wikipedia_es" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    articles = manifest["articles"]
    assert manifest["stats"]["articles"] == len(articles) > 0
    assert all(a["words"] >= manifest["filters"]["min_words"] for a in articles)
    assert len({a["pageid"] for a in articles}) == len(articles)
    assert len({a["sha256"] for a in articles}) == len(articles)
    assert all(a["url"].endswith(f"oldid={a['revid']}") for a in articles)
