"""Índice semántico FAISS persistente (DOC-13).

Usa ``HashingEncoder`` (sin descargar el modelo): comparte palabras ⇒ coseno
positivo, suficiente para comprobar persistencia, sincronización y orden.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("faiss")

from backend.app.cli import main as cli_main
from backend.app.config import Settings
from backend.app.documents.models import WIKIPEDIA_COLLECTION
from backend.app.documents.service import DocumentService
from backend.app.nlp import embeddings
from backend.app.nlp.embeddings import EmbeddingUnavailableError, HashingEncoder
from backend.app.search import semantic_index
from backend.app.search.semantic_index import SemanticIndex, SemanticIndexManager

TEXTS = {
    "volcanes.txt": "Los volcanes expulsan lava ceniza y gases durante una erupción violenta.",
    "fotosintesis.txt": "La fotosíntesis convierte luz solar en energía química dentro de las plantas.",
    "cafe.txt": "El café se cultiva en montañas tropicales y se tuesta antes de molerlo.",
}


class CountingEncoder(HashingEncoder):
    """HashingEncoder que registra cuántos textos codifica."""

    def __init__(self, dimension: int = 64) -> None:
        super().__init__(dimension)
        self.encoded: list[str] = []

    def encode(self, texts):
        self.encoded.extend(texts)
        return super().encode(texts)


@pytest.fixture()
def service(tmp_path: Path) -> DocumentService:
    settings = Settings.from_env(tmp_path / "data")
    settings.paths.ensure()
    return DocumentService(settings)


def _ingest(service: DocumentService, names=TEXTS) -> dict[str, str]:
    return {name: service.ingest(name, TEXTS[name].encode()).document.doc_id for name in names}


def _index(service: DocumentService, encoder=None, collection: str = "user") -> SemanticIndex:
    return SemanticIndex(collection, encoder or CountingEncoder(), service.settings.paths.indexes_dir / "semantic" / collection)


def test_build_search_and_persist(service: DocumentService) -> None:
    ids = _ingest(service)
    index = _index(service)
    report = index.sync(service.repository)
    assert (report.total, report.added, report.removed, report.reason) == (3, 3, 0, "missing")
    hits = index.search("erupción de lava", 3)
    assert hits[0][0].startswith(ids["volcanes.txt"])
    assert all(-1.0 <= score <= 1.0001 for _, score in hits)
    assert [s for _, s in hits] == sorted((s for _, s in hits), reverse=True)

    directory = service.settings.paths.indexes_dir / "semantic" / "user"
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    assert (directory / "index.faiss").is_file() and len(meta["entries"]) == 3
    assert meta["encoder"]["encoder"] == "hashing" and meta["version"] == index.version

    # reinicio: carga del disco sin volver a codificar
    encoder = CountingEncoder()
    reloaded = _index(service, encoder)
    report = reloaded.sync(service.repository)
    assert (report.reason, report.added, report.kept) == ("ok", 0, 3)
    assert encoder.encoded == []
    assert reloaded.version == index.version
    assert reloaded.search("erupción de lava", 3) == hits


def test_incremental_add_and_remove(service: DocumentService) -> None:
    ids = _ingest(service, ["volcanes.txt", "fotosintesis.txt"])
    encoder = CountingEncoder()
    index = _index(service, encoder)
    index.sync(service.repository)
    version = index.version

    _ingest(service, ["cafe.txt"])
    encoder.encoded.clear()
    report = index.sync(service.repository)
    assert (report.added, report.removed, report.kept, report.rebuilt) == (1, 0, 2, False)
    assert encoder.encoded == [TEXTS["cafe.txt"]]  # solo se codifica lo nuevo
    assert index.version != version

    service.repository.delete_document(ids["volcanes.txt"])
    encoder.encoded.clear()
    report = index.sync(service.repository)
    assert (report.added, report.removed, report.total) == (0, 1, 2)
    assert encoder.encoded == []
    assert not any(cid.startswith(ids["volcanes.txt"]) for cid in index.chunk_ids)
    assert not any(cid.startswith(ids["volcanes.txt"]) for cid, _ in index.search("lava volcanes", 5))
    # lo que queda en disco coincide
    assert _index(service).sync(service.repository).reason == "ok"


def test_changed_chunk_text_is_reencoded(service: DocumentService) -> None:
    ids = _ingest(service, ["cafe.txt"])
    encoder = CountingEncoder()
    index = _index(service, encoder)
    index.sync(service.repository)
    chunk = service.repository.get_chunks(ids["cafe.txt"])[0]
    service.repository.replace_chunks(ids["cafe.txt"], [chunk.model_copy(update={"text": "El té verde se cultiva en Asia."})])
    encoder.encoded.clear()
    report = index.sync(service.repository)
    assert (report.added, report.removed, report.total) == (1, 1, 1)
    assert encoder.encoded == ["El té verde se cultiva en Asia."]


@pytest.mark.parametrize(
    "damage, reason",
    [
        (lambda d: (d / "index.faiss").write_bytes(b"basura"), "checksum"),
        (lambda d: (d / "meta.json").write_text("{no json", encoding="utf-8"), "unreadable"),
        (lambda d: (d / "index.faiss").unlink(), "missing"),
    ],
)
def test_damaged_files_trigger_rebuild(service: DocumentService, damage, reason) -> None:
    _ingest(service)
    _index(service).sync(service.repository)
    damage(service.settings.paths.indexes_dir / "semantic" / "user")
    encoder = CountingEncoder()
    report = _index(service, encoder).sync(service.repository)
    assert (report.reason, report.added, report.rebuilt) == (reason, 3, True)
    assert len(encoder.encoded) == 3
    assert _index(service).sync(service.repository).reason == "ok"


def test_corrupt_faiss_payload_with_matching_checksum(service: DocumentService) -> None:
    _ingest(service)
    _index(service).sync(service.repository)
    directory = service.settings.paths.indexes_dir / "semantic" / "user"
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    (directory / "index.faiss").write_bytes(b"no es faiss")
    import hashlib

    meta["index_sha256"] = hashlib.sha256(b"no es faiss").hexdigest()
    (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert _index(service).sync(service.repository).reason == "corrupt"


def test_encoder_change_and_format_change_rebuild(service: DocumentService) -> None:
    _ingest(service)
    _index(service).sync(service.repository)
    report = _index(service, CountingEncoder(dimension=32)).sync(service.repository)
    assert (report.reason, report.added) == ("encoder_changed", 3)

    directory = service.settings.paths.indexes_dir / "semantic" / "user"
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    meta["format"] = 999
    (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert _index(service, CountingEncoder(dimension=32)).sync(service.repository).reason == "format"


def test_entries_mismatch_is_detected(service: DocumentService) -> None:
    _ingest(service)
    _index(service).sync(service.repository)
    directory = service.settings.paths.indexes_dir / "semantic" / "user"
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    meta["entries"] = meta["entries"][:1]
    (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert _index(service).sync(service.repository).reason == "mismatch"


def test_forced_rebuild_reencodes_everything(service: DocumentService) -> None:
    _ingest(service)
    _index(service).sync(service.repository)
    encoder = CountingEncoder()
    report = _index(service, encoder).sync(service.repository, rebuild=True)
    assert (report.reason, report.rebuilt, report.added, report.kept) == ("forced", True, 3, 0)
    assert len(encoder.encoded) == 3


def test_collections_are_separate(service: DocumentService) -> None:
    _ingest(service, ["volcanes.txt"])
    service.ingest_corpus_text(collection=WIKIPEDIA_COLLECTION, title="Café", text=TEXTS["cafe.txt"], filename="1.txt")
    user = _index(service).sync(service.repository)
    wiki = _index(service, collection=WIKIPEDIA_COLLECTION).sync(service.repository)
    assert user.total == 1 and wiki.total == 1
    wiki_index = _index(service, collection=WIKIPEDIA_COLLECTION)
    wiki_index.sync(service.repository)
    assert set(wiki_index.chunk_ids).isdisjoint(_index(service).chunk_ids or [])


def test_search_edge_cases(service: DocumentService) -> None:
    index = _index(service)
    assert index.sync(service.repository).total == 0
    assert index.search("lava", 5) == []  # colección vacía
    _ingest(service)
    index.sync(service.repository)
    assert index.search("", 5) == []  # el vector cero no devuelve resultados
    assert len(index.search("lava", 1)) == 1
    assert len(index.search("lava", 50)) == 3
    with pytest.raises(ValueError):
        index.search("lava", 0)
    with pytest.raises(ValueError):
        index.search_vector(np.ones(5, dtype=np.float32), 3)


def test_ties_are_broken_by_chunk_id(service: DocumentService) -> None:
    for i in range(3):
        service.ingest(f"igual_{i}.txt", f"texto idéntico número {i}".encode())
    index = _index(service, HashingEncoder(64))
    index.sync(service.repository)
    vector = HashingEncoder(64).encode(["texto idéntico"])[0]
    hits = index.search_vector(vector, 3)
    scores = [round(s, 6) for _, s in hits]
    assert scores == sorted(scores, reverse=True)
    tied = [cid for cid, s in hits if round(s, 6) == scores[0]]
    assert tied == sorted(tied)


def test_in_memory_index_without_directory(service: DocumentService) -> None:
    _ingest(service)
    index = SemanticIndex("user", HashingEncoder(), None)
    report = index.sync(service.repository)
    assert report.total == 3 and not (service.settings.paths.indexes_dir / "semantic").exists()
    assert index.describe()["chunks"] == 3 and index.describe()["metric"] == "cosine"


def test_invalid_collection_name_and_missing_faiss(monkeypatch) -> None:
    with pytest.raises(ValueError):
        SemanticIndex("../fuera", HashingEncoder(), None)

    def no_faiss():
        raise EmbeddingUnavailableError("Falta faiss-cpu (extra 'semantic')")

    monkeypatch.setattr(semantic_index, "_faiss", no_faiss)
    with pytest.raises(EmbeddingUnavailableError, match="faiss"):
        SemanticIndex("user", HashingEncoder(), None)


def test_manager_syncs_only_when_repository_changes(service: DocumentService) -> None:
    _ingest(service, ["volcanes.txt"])
    encoder = CountingEncoder()
    manager = SemanticIndexManager(service.repository, encoder, service.settings.paths.indexes_dir)
    first = manager.index("user")
    assert len(first) == 1 and manager.last_reports["user"].added == 1
    report = manager.last_reports["user"]
    assert manager.index("user") is first and manager.last_reports["user"] is report  # sin cambios: no sincroniza
    _ingest(service, ["cafe.txt"])
    assert len(manager.index("user")) == 2 and manager.last_reports["user"].added == 1
    assert manager.rebuild("user").rebuilt is True


def test_cli_semantic_index(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(tmp_path / "data"))
    service = DocumentService(Settings.from_env())
    service.ingest("volcanes.txt", TEXTS["volcanes.txt"].encode())
    monkeypatch.setattr(embeddings, "get_encoder", lambda: HashingEncoder())
    assert cli_main(["semantic-index"]) == 0
    reports = {r["collection"]: r for r in json.loads(capsys.readouterr().out)["indexes"]}
    assert reports["user"]["added"] == 1 and reports[WIKIPEDIA_COLLECTION]["total"] == 0
    assert cli_main(["semantic-index", "--collection", "user"]) == 0
    assert json.loads(capsys.readouterr().out)["indexes"][0]["added"] == 0
    assert cli_main(["semantic-index", "--collection", "user", "--rebuild"]) == 0
    assert json.loads(capsys.readouterr().out)["indexes"][0]["reason"] == "forced"


def test_cli_semantic_index_without_extra(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(tmp_path / "data"))

    def unavailable():
        raise EmbeddingUnavailableError("Falta el extra 'semantic'")

    monkeypatch.setattr(semantic_index, "_faiss", unavailable)
    monkeypatch.setattr(embeddings, "get_encoder", lambda: HashingEncoder())
    assert cli_main(["semantic-index"]) == 1
    assert "semantic" in capsys.readouterr().err
