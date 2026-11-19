"""Conjunto de evaluación MIRACL en español, anotado por personas (DOC-16).

MIRACL (Zhang et al., TACL 2023; licencia Apache-2.0) contiene consultas
escritas por hablantes nativos y pasajes de Wikipedia en español juzgados como
relevantes o no relevantes por anotadores humanos.

Para no descargar el corpus completo (1,5 GB), se usa la conversión a parquet
del split ``dev`` (2,6 MB), que ya incluye el texto de los pasajes juzgados.
El corpus de evaluación (colección ``miracl_es``) es la **unión de los pasajes
juzgados de todas las consultas** (*pooling*): para cada consulta, los pasajes
juzgados de las demás actúan como distractores y se consideran no relevantes.

Por eso las cifras **no son comparables** con la clasificación oficial de
MIRACL, que busca en toda la Wikipedia en español. Ver ``docs/evaluacion.md``.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MIRACL_COLLECTION = "miracl_es"
PARQUET_REVISION = "ad2acf33f265b8fba92e5096c9d2cf569a82b067"  # refs/convert/parquet de miracl/miracl
PARQUET_URL = f"https://huggingface.co/datasets/miracl/miracl/resolve/{PARQUET_REVISION}/es/dev/0000.parquet"
PARQUET_SHA256 = "23b5bd51a3b4807aa627095b5021c1b36aa2e91d85f86df8f6e478b83dd4a0ca"
USER_AGENT = "DocuSearch-AI/0.2 (evaluation dataset download)"


class MiraclError(RuntimeError):
    """Descarga, verificación o lectura fallida."""


@dataclass(frozen=True)
class Passage:
    docid: str
    title: str
    text: str

    @property
    def unique_title(self) -> str:
        """Título único por pasaje (un artículo tiene varios pasajes)."""
        return f"{self.title} [{self.docid}]"[:500]

    @property
    def indexed_text(self) -> str:
        """Título + texto, como en las líneas base oficiales de MIRACL."""
        return f"{self.title}\n{self.text}" if self.title else self.text


@dataclass(frozen=True)
class MiraclQuery:
    qid: str
    query: str
    positives: tuple[str, ...]
    negatives: tuple[str, ...]


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 (URL fija)
        return response.read()


def ensure_parquet(destination: Path) -> Path:
    """Descarga (si falta) el parquet fijado y verifica su SHA-256."""
    if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == PARQUET_SHA256:
        return destination
    try:
        data = _download(PARQUET_URL)
    except OSError as exc:
        raise MiraclError(f"no se pudo descargar MIRACL: {exc}") from exc
    digest = hashlib.sha256(data).hexdigest()
    if digest != PARQUET_SHA256:
        raise MiraclError(f"SHA-256 inesperado del parquet de MIRACL: {digest}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=destination.parent, prefix=".tmp-miracl-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, destination)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return destination


def read_parquet(path: Path) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise MiraclError("falta pyarrow: python -m pip install -e \".[eval]\"") from exc
    return pq.read_table(path).to_pylist()


def parse_rows(rows: Iterable[dict[str, Any]]) -> tuple[list[MiraclQuery], dict[str, Passage]]:
    """Consultas y pasajes únicos (por ``docid``) del split."""
    queries: list[MiraclQuery] = []
    passages: dict[str, Passage] = {}
    for row in rows:
        positives, negatives = [], []
        for field, target in (("positive_passages", positives), ("negative_passages", negatives)):
            for item in row.get(field) or []:
                passage = Passage(str(item["docid"]), (item.get("title") or "").strip(), (item.get("text") or "").strip())
                if not passage.text:
                    continue
                passages.setdefault(passage.docid, passage)
                target.append(passage.docid)
        if positives:
            queries.append(MiraclQuery(str(row["query_id"]), str(row["query"]).strip(), tuple(positives), tuple(negatives)))
    return queries, passages


def queries_file_payload(queries: list[MiraclQuery], passages: dict[str, Passage]) -> dict[str, Any]:
    """Consultas en el formato de ``evaluation.load_queries`` (relevancia por título único)."""
    return {
        "name": "miracl_es_dev",
        "description": (
            "MIRACL v1.0, español, split dev (Zhang et al., 2023; Apache-2.0). Consultas de hablantes nativos y "
            "relevancia juzgada por personas. Corpus = unión de los pasajes juzgados (pooling)."
        ),
        "annotator": "humano (MIRACL)",
        "source": {"dataset": "miracl/miracl", "revision": PARQUET_REVISION, "sha256": PARQUET_SHA256},
        "relevance": "binaria, por pasaje",
        "queries": [
            {
                "id": q.qid,
                "split": "test",
                "type": "miracl",
                "query": q.query,
                "relevant": [passages[d].unique_title for d in q.positives],
            }
            for q in queries
        ],
    }


def import_miracl(service: Any, queries: list[MiraclQuery], passages: dict[str, Passage]) -> dict[str, int]:
    """Registra los pasajes en la colección ``miracl_es`` (idempotente)."""
    from backend.app.documents.repository import DuplicateDocumentError

    imported = skipped = 0
    for passage in passages.values():
        try:
            service.ingest_corpus_text(
                collection=MIRACL_COLLECTION,
                title=passage.unique_title,
                text=passage.indexed_text,
                filename=f"{passage.docid.replace('#', '_')}.txt",
                source_uri=f"miracl:es:{passage.docid}",
                metadata={"miracl_docid": passage.docid},
            )
            imported += 1
        except DuplicateDocumentError:
            skipped += 1
    return {"queries": len(queries), "passages": len(passages), "imported": imported, "already_present": skipped}


def write_queries(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
