"""Corpus léxico tokenizado para los índices TF-IDF y BM25 (DOC-08).

Los fragmentos se leen del repositorio en orden estable (``doc_id``,
``ordinal``) y se tokenizan con el pipeline léxico de DOC-06. Como lematizar
es lo más costoso, los tokens se guardan en una caché JSON (no ``pickle``)
en ``data/indexes/``, invalidada si cambia el texto del fragmento o la
configuración del pipeline.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.documents.models import Chunk
from backend.app.documents.repository import DocumentRepository
from backend.app.nlp.lexical import LexicalPipeline

CACHE_FORMAT = 1


def _text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def config_fingerprint(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]


class TokenCache:
    """Caché persistente ``chunk_id → tokens`` para una configuración léxica."""

    def __init__(self, path: Path | None, pipeline_config: dict[str, Any]) -> None:
        self.path = path
        self.fingerprint = config_fingerprint(pipeline_config)
        self.entries: dict[str, dict[str, Any]] = {}
        self.dirty = False
        if path is not None and path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("format") == CACHE_FORMAT and data.get("pipeline") == self.fingerprint:
                    self.entries = data.get("entries", {})
            except (OSError, ValueError):
                self.entries = {}

    def get(self, chunk: Chunk) -> list[str] | None:
        entry = self.entries.get(chunk.chunk_id)
        if entry and entry.get("h") == _text_hash(chunk.text):
            return list(entry["t"])
        return None

    def put(self, chunk: Chunk, tokens: list[str]) -> None:
        self.entries[chunk.chunk_id] = {"h": _text_hash(chunk.text), "t": tokens}
        self.dirty = True

    def prune(self, keep: set[str]) -> None:
        stale = [k for k in self.entries if k not in keep]
        for key in stale:
            del self.entries[key]
        self.dirty = self.dirty or bool(stale)

    def save(self) -> None:
        if self.path is None or not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"format": CACHE_FORMAT, "pipeline": self.fingerprint, "entries": self.entries}
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".tmp-tokens-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self.dirty = False


@dataclass(frozen=True)
class LexicalCorpus:
    """Fragmentos de una colección con sus tokens léxicos, en orden estable."""

    collection: str | None
    chunks: tuple[Chunk, ...]
    tokens: tuple[tuple[str, ...], ...]
    version: str

    def __len__(self) -> int:
        return len(self.chunks)

    @property
    def chunk_ids(self) -> tuple[str, ...]:
        return tuple(c.chunk_id for c in self.chunks)


def build_lexical_corpus(
    repository: DocumentRepository,
    pipeline: LexicalPipeline,
    collection: str | None,
    cache_path: Path | None = None,
) -> LexicalCorpus:
    """Lee y tokeniza los fragmentos de ``collection`` usando la caché."""
    chunks = list(repository.iter_chunks(collection))
    cache = TokenCache(cache_path, pipeline.config)
    tokens: list[list[str] | None] = [cache.get(c) for c in chunks]
    missing = [i for i, t in enumerate(tokens) if t is None]
    if missing:
        processed = pipeline.process_many(chunks[i].text for i in missing)
        for index, result in zip(missing, processed):
            tokens[index] = result
            cache.put(chunks[index], result)
    if collection is None:
        cache.prune({c.chunk_id for c in chunks})
    cache.save()

    digest = hashlib.sha256()
    digest.update(cache.fingerprint.encode())
    for chunk in chunks:
        digest.update(f"{chunk.chunk_id}:{_text_hash(chunk.text)};".encode())
    return LexicalCorpus(
        collection=collection,
        chunks=tuple(chunks),
        tokens=tuple(tuple(t or ()) for t in tokens),
        version=digest.hexdigest()[:16],
    )
