"""Retirada inmediata de datos derivados de un documento eliminado (DOC-30).

Al borrar un documento no basta con quitar sus filas de SQLite: su texto
tokenizado queda en la caché léxica (``lexical_tokens.json``) y sus vectores
en el índice FAISS en disco hasta la siguiente sincronización. Aquí se
purgan ambos **sin cargar el modelo de embeddings** (solo hace falta FAISS
para reescribir el índice). Si el índice no se puede purgar con seguridad
(checksum, formato), se elimina para que se reconstruya.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

from .semantic_index import INDEX_FILE, INDEX_FORMAT, META_FILE, _atomic_write


def purge_token_cache(cache_path: Path, chunk_ids: set[str]) -> int:
    """Quita de la caché léxica los tokens de ``chunk_ids``; devuelve cuántos."""
    if not chunk_ids or not cache_path.is_file():
        return 0
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache_path.unlink(missing_ok=True)  # caché ilegible: se regenera
        return 0
    entries = data.get("entries", {})
    removed = [key for key in entries if key in chunk_ids]
    if not removed:
        return 0
    for key in removed:
        del entries[key]
    _atomic_write(cache_path, json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return len(removed)


def _drop_index(directory: Path) -> None:
    for name in (INDEX_FILE, META_FILE):
        (directory / name).unlink(missing_ok=True)


def purge_semantic_index(directory: Path, chunk_ids: set[str]) -> str:
    """Quita del índice FAISS en disco los vectores de ``chunk_ids``.

    Devuelve ``absent`` (no hay índice), ``unchanged``, ``purged`` o
    ``dropped`` (se borró para reconstruirlo; p. ej. sin faiss o checksum
    inválido). Nunca deja vectores de los fragmentos eliminados.
    """
    index_path, meta_path = directory / INDEX_FILE, directory / META_FILE
    if not index_path.is_file() and not meta_path.is_file():
        return "absent"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        data = index_path.read_bytes()
    except (OSError, ValueError):
        _drop_index(directory)
        return "dropped"
    entries: list[dict[str, Any]] = meta.get("entries", [])
    keep = [i for i, entry in enumerate(entries) if entry.get("chunk_id") not in chunk_ids]
    if len(keep) == len(entries):
        return "unchanged"
    try:
        import faiss
    except ImportError:
        _drop_index(directory)
        return "dropped"
    if meta.get("format") != INDEX_FORMAT or meta.get("index_sha256") != hashlib.sha256(data).hexdigest():
        _drop_index(directory)
        return "dropped"
    try:
        index = faiss.deserialize_index(np.frombuffer(data, dtype=np.uint8))
        if index.ntotal != len(entries):
            raise ValueError("índice y metadatos no coinciden")
        vectors = index.reconstruct_n(0, index.ntotal)[keep] if keep else np.zeros((0, index.d), dtype=np.float32)
        rebuilt = faiss.IndexFlatIP(index.d)
        if len(vectors):
            rebuilt.add(np.ascontiguousarray(vectors, dtype=np.float32))
    except Exception:
        _drop_index(directory)
        return "dropped"
    kept_entries = [entries[i] for i in keep]
    serialized = faiss.serialize_index(rebuilt).tobytes()
    digest = hashlib.sha256(str(meta.get("encoder_fingerprint", "")).encode())
    for entry in sorted(kept_entries, key=lambda e: e["chunk_id"]):
        digest.update(f"{entry['chunk_id']}:{entry['h']};".encode())
    meta.update(
        entries=kept_entries,
        index_sha256=hashlib.sha256(serialized).hexdigest(),
        version=digest.hexdigest()[:16],
        updated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )
    _atomic_write(index_path, serialized)
    _atomic_write(meta_path, json.dumps(meta, ensure_ascii=False).encode("utf-8"))
    return "purged"


def forget_chunks(indexes_dir: Path, collection: str, chunk_ids: Iterable[str], engine: Any = None) -> dict[str, Any]:
    """Purga caché léxica e índice semántico e invalida el estado en memoria."""
    ids = set(chunk_ids)
    lock = getattr(engine, "_lock", None)
    if lock is not None:
        lock.acquire()
    try:
        tokens = purge_token_cache(indexes_dir / "lexical_tokens.json", ids)
        semantic = purge_semantic_index(indexes_dir / "semantic" / collection, ids)
        if engine is not None:
            engine.forget(collection)
    finally:
        if lock is not None:
            lock.release()
    return {"lexical": "rebuild_on_next_search", "lexical_cache_entries_removed": tokens, "semantic": semantic}
