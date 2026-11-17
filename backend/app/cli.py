"""Comandos de mantenimiento de DocuSearch AI.

Uso (desde la raíz del repositorio)::

    python -m backend.app.cli rechunk [--collection user]

Los comandos usan la misma configuración que la API (variables
``DOCUSEARCH_*``) y operan solo sobre el directorio de datos local.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from backend.app.config import Settings
from backend.app.documents.service import DocumentService


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backend.app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    rechunk = sub.add_parser("rechunk", help="volver a extraer y fragmentar desde los originales")
    rechunk.add_argument("--collection", default=None, help="colección (por defecto, todas)")
    rechunk.set_defaults(func=_cmd_rechunk)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
