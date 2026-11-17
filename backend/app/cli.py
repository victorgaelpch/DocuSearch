"""Comandos de mantenimiento de DocuSearch AI.

Uso (desde la raíz del repositorio)::

    python -m backend.app.cli rechunk [--collection user]
    python -m backend.app.cli corpus freeze|build|import|stats

Los comandos usan la misma configuración que la API (variables
``DOCUSEARCH_*``) y operan solo sobre el directorio de datos local.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

import os
from pathlib import Path

from backend.app.config import Settings
from backend.app.documents.models import WIKIPEDIA_COLLECTION
from backend.app.documents.repository import DuplicateDocumentError
from backend.app.documents.service import DocumentService

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "corpus" / "wikipedia_es"


def _cmd_rechunk(args: argparse.Namespace) -> int:
    service = DocumentService(Settings.from_env())
    report = service.rechunk(args.collection)
    print(
        json.dumps(
            {
                "documents": report.documents,
                "chunks": report.chunks,
                "failed": report.failed,
                "chunking": service.chunking.as_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report.failed else 0


def _corpus_paths(settings: Settings) -> tuple[Path, Path, Path]:
    return (
        CORPUS_DIR / "topics.json",
        CORPUS_DIR / "manifest.json",
        settings.paths.root / "corpus" / "wikipedia_es",
    )


def _client():
    from backend.app.corpus.wikipedia import DEFAULT_USER_AGENT, USER_AGENT_ENV, WikipediaClient

    return WikipediaClient(user_agent=os.environ.get(USER_AGENT_ENV) or DEFAULT_USER_AGENT)


def _cmd_corpus(args: argparse.Namespace) -> int:
    from backend.app.corpus import wikipedia

    settings = Settings.from_env()
    topics, manifest, texts = _corpus_paths(settings)
    if args.action == "freeze":
        result = wikipedia.freeze(_client(), topics, manifest, texts, min_words=args.min_words)
        print(json.dumps(result["stats"], ensure_ascii=False, indent=2))
    elif args.action == "build":
        wikipedia.build(_client(), manifest, texts)
    elif args.action == "stats":
        data = json.loads(manifest.read_text(encoding="utf-8"))
        print(json.dumps(data["stats"], ensure_ascii=False, indent=2))
    elif args.action == "import":
        service = DocumentService(settings)
        imported = skipped = 0
        for article, text in wikipedia.iter_corpus_texts(manifest, texts):
            try:
                service.ingest_corpus_text(
                    collection=WIKIPEDIA_COLLECTION,
                    title=article["title"],
                    text=text,
                    filename=f"{article['pageid']}.txt",
                    source_uri=article["url"],
                    metadata={
                        "topic": article["topic"],
                        "pageid": article["pageid"],
                        "revid": article["revid"],
                        "license": wikipedia.LICENSE,
                    },
                )
                imported += 1
            except DuplicateDocumentError:
                skipped += 1
        print(json.dumps({"imported": imported, "already_present": skipped}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backend.app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    rechunk = sub.add_parser("rechunk", help="volver a extraer y fragmentar desde los originales")
    rechunk.add_argument("--collection", default=None, help="colección (por defecto, todas)")
    rechunk.set_defaults(func=_cmd_rechunk)
    corpus = sub.add_parser("corpus", help="corpus experimental de Wikipedia en español")
    corpus.add_argument("action", choices=["freeze", "build", "import", "stats"])
    corpus.add_argument("--min-words", type=int, default=50)
    corpus.set_defaults(func=_cmd_corpus)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
