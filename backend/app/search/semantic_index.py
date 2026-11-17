"""Índice semántico FAISS persistente y versionado por colección (DOC-13).

Guarda los embeddings de los fragmentos (DOC-12) en un ``faiss.IndexFlatIP``.
Como los vectores están normalizados, el producto interno es el coseno y la
búsqueda es exacta (fuerza bruta), suficiente para decenas de miles de
fragmentos en CPU.

Persistencia en ``data/indexes/semantic/<colección>/`` (nunca en Git):

* ``index.faiss``: índice serializado con ``faiss.serialize_index`` (se
  escribe con Python para admitir rutas con tildes en Windows).
* ``meta.json``: formato, configuración y huella del codificador, y por cada
  posición del índice su ``chunk_id`` y el hash del texto, más el SHA-256 del
  índice para detectar archivos incompletos o de otra versión.

Sincronización: al detectar un cambio, solo se codifican los fragmentos
nuevos o con texto distinto; los borrados se eliminan. Si cambia el
codificador (modelo, revisión, estrategia, pipeline) o el archivo no es
válido, el índice se reconstruye desde cero.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from backend.app.documents.repository import DocumentRepository
from backend.app.nlp.embeddings import Encoder, EmbeddingUnavailableError

from .lexical_corpus import config_fingerprint

INDEX_FORMAT = 1
INDEX_FILE = "index.faiss"
META_FILE = "meta.json"
_COLLECTION_NAME = re.compile(r"^[a-z0-9_]+$")


def _faiss() -> Any:
    try:
        import faiss
    except ImportError as exc:
        raise EmbeddingUnavailableError(
            "Falta faiss-cpu (extra 'semantic'): python -m pip install -e \".[semantic]\""
        ) from exc
    return faiss


def _text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".tmp-{path.name}-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class SyncReport:
    """Resultado de sincronizar el índice con el repositorio."""

    collection: str
    total: int
    added: int
    removed: int
    kept: int
    rebuilt: bool
    reason: str
    seconds: float
    version: str

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class SemanticIndex:
    """Índice FAISS de los fragmentos de una colección."""

    def __init__(self, collection: str, encoder: Encoder, directory: Path | None = None) -> None:
        if not _COLLECTION_NAME.match(collection):
            raise ValueError(f"nombre de colección no válido: {collection!r}")
        self.collection = collection
        self.encoder = encoder
        self.directory = directory
        self._faiss = _faiss()
        self._index: Any = None
        self._entries: list[dict[str, str]] = []
        self._loaded = False
        self._lock = threading.RLock()

    # -- metadatos ---------------------------------------------------------
    @property
    def encoder_fingerprint(self) -> str:
        return config_fingerprint(self.encoder.config)

    @property
    def chunk_ids(self) -> list[str]:
        return [entry["chunk_id"] for entry in self._entries]

    @property
    def version(self) -> str:
        digest = hashlib.sha256(self.encoder_fingerprint.encode())
        for entry in sorted(self._entries, key=lambda e: e["chunk_id"]):
            digest.update(f"{entry['chunk_id']}:{entry['h']};".encode())
        return digest.hexdigest()[:16]

    def __len__(self) -> int:
        return len(self._entries)

    def describe(self) -> dict[str, Any]:
        return {
            "method": "semantic",
            "collection": self.collection,
            "index": "faiss.IndexFlatIP",
            "metric": "cosine",
            "chunks": len(self),
            "dimension": self.encoder.dimension,
            "version": self.version,
            "encoder": self.encoder.config,
        }

    # -- persistencia ------------------------------------------------------
    def _paths(self) -> tuple[Path, Path] | None:
        if self.directory is None:
            return None
        return self.directory / INDEX_FILE, self.directory / META_FILE

    def _empty(self) -> Any:
        return self._faiss.IndexFlatIP(self.encoder.dimension)

    def load(self) -> str:
        """Carga el índice del disco. Devuelve ``"ok"`` o el motivo de descartarlo."""
        with self._lock:
            self._loaded = True
            self._index, self._entries = self._empty(), []
            paths = self._paths()
            if paths is None or not paths[0].is_file() or not paths[1].is_file():
                return "missing"
            index_path, meta_path = paths
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                data = index_path.read_bytes()
            except (OSError, ValueError):
                return "unreadable"
            if meta.get("format") != INDEX_FORMAT:
                return "format"
            if meta.get("encoder_fingerprint") != self.encoder_fingerprint:
                return "encoder_changed"
            if meta.get("index_sha256") != hashlib.sha256(data).hexdigest():
                return "checksum"
            try:
                index = self._faiss.deserialize_index(np.frombuffer(data, dtype=np.uint8))
            except Exception:  # archivo FAISS corrupto
                return "corrupt"
            entries = meta.get("entries", [])
            if index.ntotal != len(entries) or index.d != self.encoder.dimension:
                return "mismatch"
            self._index, self._entries = index, entries
            return "ok"

    def save(self) -> None:
        paths = self._paths()
        if paths is None:
            return
        index_path, meta_path = paths
        self.directory.mkdir(parents=True, exist_ok=True)
        data = self._faiss.serialize_index(self._index).tobytes()
        meta = {
            "format": INDEX_FORMAT,
            "collection": self.collection,
            "encoder_fingerprint": self.encoder_fingerprint,
            "encoder": self.encoder.config,
            "index": "IndexFlatIP",
            "index_sha256": hashlib.sha256(data).hexdigest(),
            "version": self.version,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "entries": self._entries,
        }
        # primero el índice; el checksum de meta.json detecta una escritura a medias
        _atomic_write(index_path, data)
        _atomic_write(meta_path, json.dumps(meta, ensure_ascii=False).encode("utf-8"))

    # -- sincronización ----------------------------------------------------
    def sync(self, repository: DocumentRepository, *, rebuild: bool = False) -> SyncReport:
        """Alinea el índice con los fragmentos actuales de la colección."""
        started = time.perf_counter()
        with self._lock:
            reason = "forced" if rebuild else (self.load() if not self._loaded else "ok")
            if rebuild:
                self._index, self._entries, self._loaded = self._empty(), [], True
            chunks = list(repository.iter_chunks(self.collection))
            current = {c.chunk_id: _text_hash(c.text) for c in chunks}
            keep = [i for i, e in enumerate(self._entries) if current.get(e["chunk_id"]) == e["h"]]
            kept_ids = {self._entries[i]["chunk_id"] for i in keep}
            new_chunks = [c for c in chunks if c.chunk_id not in kept_ids]
            removed = len(self._entries) - len(keep)

            changed = bool(new_chunks) or removed > 0
            if removed:
                vectors = (
                    self._index.reconstruct_n(0, self._index.ntotal)[keep]
                    if keep else np.zeros((0, self.encoder.dimension), dtype=np.float32)
                )
                index = self._empty()
                if len(vectors):
                    index.add(vectors)
                self._index = index
                self._entries = [self._entries[i] for i in keep]
            if new_chunks:
                vectors = np.ascontiguousarray(self.encoder.encode([c.text for c in new_chunks]), dtype=np.float32)
                self._index.add(vectors)
                self._entries.extend({"chunk_id": c.chunk_id, "h": current[c.chunk_id]} for c in new_chunks)
            paths = self._paths()
            if changed or (paths is not None and reason != "ok"):
                self.save()
            return SyncReport(
                collection=self.collection,
                total=len(self._entries),
                added=len(new_chunks),
                removed=removed,
                kept=len(keep),
                rebuilt=rebuild or (reason != "ok" and bool(new_chunks)),
                reason=reason,
                seconds=round(time.perf_counter() - started, 3),
                version=self.version,
            )

    # -- búsqueda ----------------------------------------------------------
    def search_vector(self, vector: np.ndarray, k: int) -> list[tuple[str, float]]:
        """``(chunk_id, coseno)`` de los ``k`` vecinos más cercanos, en orden."""
        if k < 1:
            raise ValueError("k debe ser mayor que 0")
        with self._lock:
            if self._index is None or not len(self._entries):
                return []
            query = np.ascontiguousarray(np.asarray(vector, dtype=np.float32).reshape(1, -1))
            if query.shape[1] != self.encoder.dimension:
                raise ValueError("dimensión de la consulta distinta de la del índice")
            if not np.any(query):
                return []  # consulta vacía: el vector cero no se parece a nada
            # pide algunos de más para desempatar de forma estable por chunk_id
            n = min(len(self._entries), k + 10)
            scores, positions = self._index.search(query, n)
            pairs = [
                (self._entries[p]["chunk_id"], float(s))
                for s, p in zip(scores[0], positions[0])
                if p >= 0
            ]
        pairs.sort(key=lambda item: (-round(item[1], 6), item[0]))
        return pairs[:k]

    def search(self, query: str, k: int) -> list[tuple[str, float]]:
        return self.search_vector(self.encoder.encode([query])[0], k)


class SemanticIndexManager:
    """Un índice por colección, sincronizado cuando cambia el repositorio."""

    def __init__(self, repository: DocumentRepository, encoder: Encoder, indexes_dir: Path | None) -> None:
        self.repository = repository
        self.encoder = encoder
        self.base_dir = None if indexes_dir is None else indexes_dir / "semantic"
        self._indexes: dict[str, SemanticIndex] = {}
        self._signatures: dict[str, tuple[Any, ...]] = {}
        self.last_reports: dict[str, SyncReport] = {}
        self._lock = threading.RLock()

    def _get(self, collection: str) -> SemanticIndex:
        index = self._indexes.get(collection)
        if index is None:
            directory = None if self.base_dir is None else self.base_dir / collection
            index = SemanticIndex(collection, self.encoder, directory)
            self._indexes[collection] = index
        return index

    def index(self, collection: str) -> SemanticIndex:
        """Índice actualizado de ``collection`` (sincroniza solo si hubo cambios)."""
        signature = self.repository.collection_signature(collection)
        with self._lock:
            index = self._get(collection)
            if self._signatures.get(collection) != signature:
                self.last_reports[collection] = index.sync(self.repository)
                self._signatures[collection] = signature
            return index

    def rebuild(self, collection: str) -> SyncReport:
        with self._lock:
            signature = self.repository.collection_signature(collection)
            report = self._get(collection).sync(self.repository, rebuild=True)
            self._signatures[collection] = signature
            self.last_reports[collection] = report
            return report
