"""Comandos de mantenimiento de DocuSearch AI.

Uso (desde la raíz del repositorio)::

    python -m backend.app.cli rechunk [--collection user]
    python -m backend.app.cli corpus freeze|build|import|stats
    python -m backend.app.cli evaluate [--output evaluation/results/x.json]
    python -m backend.app.cli reindex [--collection user] [--semantic]
    python -m backend.app.cli benchmark [--repeats 5]
    python -m backend.app.cli embeddings [--collection wikipedia_es] [--limit 200]
    python -m backend.app.cli semantic-index [--collection wikipedia_es] [--rebuild]
    python -m backend.app.cli ocr [--collection user]
    python -m backend.app.cli tessdata [--variant fast] [--languages spa eng]
    python -m backend.app.cli miracl
    python -m backend.app.cli hash-password [--stdin]

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


def _search_engine(settings: Settings, long_text: str | None = None):
    """Motor de búsqueda; ``long_text`` distinto de ``mean`` usa otro codificador e índice aparte."""
    from backend.app.search.engine import SearchEngine

    service = DocumentService(settings)
    indexes_dir = settings.paths.indexes_dir
    encoder_factory = None
    if long_text and long_text != "mean":
        import dataclasses

        from backend.app.nlp.embeddings import EmbeddingConfig, SentenceTransformerEncoder

        config = dataclasses.replace(EmbeddingConfig.from_env(), long_text=long_text)

        def encoder_factory():
            return SentenceTransformerEncoder(config)

        indexes_dir = settings.paths.indexes_dir / f"experiment-{long_text}"
    return SearchEngine(
        service.repository,
        cache_path=settings.paths.indexes_dir / "lexical_tokens.json",
        indexes_dir=indexes_dir,
        encoder_factory=encoder_factory,
    )


def _cmd_reindex(args: argparse.Namespace) -> int:
    """Refragmenta desde los originales y reconstruye los índices léxicos."""
    settings = Settings.from_env()
    service = DocumentService(settings)
    report = service.rechunk(args.collection)
    engine = _search_engine(settings)
    collections = [args.collection] if args.collection else ["user", WIKIPEDIA_COLLECTION]
    indexes = [engine.rebuild(c) for c in collections]
    semantic = None
    if args.semantic:
        from backend.app.nlp.embeddings import EmbeddingUnavailableError

        try:
            semantic = [engine.rebuild_semantic(c) for c in collections]
        except EmbeddingUnavailableError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    print(
        json.dumps(
            {
                "rechunk": {"documents": report.documents, "chunks": report.chunks, "failed": report.failed},
                "indexes": indexes,
                **({"semantic": semantic} if semantic is not None else {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report.failed else 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    from backend.app.search.evaluation import compare_methods, evaluate, format_table, load_queries

    settings = Settings.from_env()
    queries, meta = load_queries(Path(args.queries), split=args.split)
    engine = _search_engine(settings, long_text=args.long_text)
    engine.describe(args.collection)  # construye los índices fuera de la medición
    if {"semantic", "hybrid"} & set(args.methods):
        engine.semantic.index(args.collection)
    report = evaluate(engine, queries, methods=args.methods, collection=args.collection)
    report["queries_file"] = meta.get("name")
    report["split"] = args.split or "all"
    if args.long_text:
        report["long_text"] = args.long_text
    if args.baseline in args.methods and len(args.methods) > 1:
        report["significance"] = compare_methods(report, args.baseline)
    print(format_table(report))
    for method, metrics in report.get("significance", {}).get("comparisons", {}).items():
        for metric, values in metrics.items():
            print(
                f"{method} vs {args.baseline} {metric}: diferencia {values['mean_difference']:+.4f} "
                f"(gana {values['wins']}, pierde {values['losses']}, p={values['p_value']:.4f})"
            )
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"resultados guardados en {output}")
    return 0


def _cmd_benchmark(args: argparse.Namespace) -> int:
    from backend.app.search.evaluation import benchmark_latency, load_queries

    settings = Settings.from_env()
    queries, _ = load_queries(Path(args.queries))
    from backend.app.nlp.embeddings import EmbeddingUnavailableError

    try:
        report = benchmark_latency(
            _search_engine(settings),
            [q.query for q in queries],
            methods=args.methods,
            collection=args.collection,
            repeats=args.repeats,
        )
    except EmbeddingUnavailableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(m["under_2s"] for m in report["methods"].values()) else 1


def _cmd_embeddings(args: argparse.Namespace) -> int:
    """Carga el modelo de embeddings y, opcionalmente, mide la codificación."""
    import time

    from backend.app.documents.repository import DocumentRepository
    from backend.app.nlp.embeddings import EmbeddingUnavailableError, get_encoder

    encoder = get_encoder()
    started = time.perf_counter()
    try:
        config = encoder.config  # fuerza la carga del modelo
    except EmbeddingUnavailableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    report: dict = {"config": config, "load_seconds": round(time.perf_counter() - started, 2)}
    if args.collection:
        repository = DocumentRepository(Settings.from_env().paths.metadata_db)
        texts = [chunk.text for chunk in repository.iter_chunks(collection=args.collection)]
        if args.limit:
            texts = texts[: args.limit]
        started = time.perf_counter()
        vectors = encoder.encode(texts)
        elapsed = time.perf_counter() - started
        report["encoding"] = {
            "collection": args.collection,
            "chunks": len(texts),
            "seconds": round(elapsed, 2),
            "chunks_per_second": round(len(texts) / elapsed, 1) if elapsed else None,
            "shape": list(vectors.shape),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_semantic_index(args: argparse.Namespace) -> int:
    """Construye o sincroniza el índice FAISS de una o varias colecciones."""
    from backend.app.documents.models import DEFAULT_COLLECTION
    from backend.app.documents.repository import DocumentRepository
    from backend.app.nlp import embeddings
    from backend.app.search.semantic_index import SemanticIndexManager

    settings = Settings.from_env()
    settings.paths.ensure()
    collections = args.collection or [DEFAULT_COLLECTION, WIKIPEDIA_COLLECTION]
    try:
        manager = SemanticIndexManager(
            DocumentRepository(settings.paths.metadata_db), embeddings.get_encoder(), settings.paths.indexes_dir
        )
        reports = []
        for collection in collections:
            if args.rebuild:
                reports.append(manager.rebuild(collection).as_dict())
            else:
                manager.index(collection)
                reports.append(manager.last_reports[collection].as_dict())
    except embeddings.EmbeddingUnavailableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"indexes": reports}, ensure_ascii=False, indent=2))
    return 0


def _cmd_ocr(args: argparse.Namespace) -> int:
    """Reprocesa con OCR los documentos que quedaron como ``needs_ocr``."""
    from backend.app.documents.ocr import get_ocr

    ocr = get_ocr()
    if ocr is None:
        print("error: OCR no disponible (Tesseract no encontrado o DOCUSEARCH_OCR=off); ver docs/lectores.md",
              file=sys.stderr)
        return 1
    report = DocumentService(Settings.from_env()).process_pending_ocr(args.collection)
    language, warnings = ocr.resolve_language()
    print(json.dumps({"ocr": {**ocr.engine, "language": language, "warnings": warnings},
                      "pending": report.pending, "recognized": report.recognized,
                      "still_pending": report.still_pending, "failed": report.failed},
                     ensure_ascii=False, indent=2))
    return 1 if report.failed else 0


def _cmd_tessdata(args: argparse.Namespace) -> int:
    """Instala idiomas de Tesseract en data/tessdata (commit fijado y SHA-256 verificado)."""
    from backend.app.documents.tessdata import TessdataError, install_languages

    settings = Settings.from_env()
    try:
        report = install_languages(settings.paths.root / "tessdata", args.languages, args.variant)
    except TessdataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_miracl(args: argparse.Namespace) -> int:
    """Descarga MIRACL-es (dev) y lo importa como colección ``miracl_es`` (DOC-16)."""
    from backend.app.corpus import miracl

    settings = Settings.from_env()
    base = settings.paths.root / "miracl"
    try:
        rows = miracl.read_parquet(miracl.ensure_parquet(base / "miracl-es-dev.parquet"))
    except miracl.MiraclError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    queries, passages = miracl.parse_rows(rows)
    queries_path = base / "queries_miracl_es_dev.json"
    miracl.write_queries(queries_path, miracl.queries_file_payload(queries, passages))
    report = miracl.import_miracl(DocumentService(settings), queries, passages)
    print(json.dumps({**report, "queries_file": str(queries_path)}, ensure_ascii=False, indent=2))
    return 0


def _cmd_hash_password(args: argparse.Namespace) -> int:
    """Genera el hash scrypt para DOCUSEARCH_ADMIN/USER_PASSWORD_HASH (DOC-25).

    La contraseña se pide sin eco (o se lee de stdin) y nunca se imprime.
    """
    import getpass

    from backend.app.auth.passwords import hash_password

    if args.stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("Contraseña (mínimo 12 caracteres): ")
        if getpass.getpass("Repita la contraseña: ") != password:
            print("Las contraseñas no coinciden.", file=sys.stderr)
            return 1
    try:
        print(hash_password(password))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
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
    reindex = sub.add_parser("reindex", help="refragmentar y reconstruir los índices de búsqueda")
    reindex.add_argument("--collection", default=None, help="colección (por defecto, todas)")
    reindex.add_argument("--semantic", action="store_true", help="reconstruir también el índice semántico FAISS")
    reindex.set_defaults(func=_cmd_reindex)
    evaluate = sub.add_parser("evaluate", help="evaluar métodos con consultas anotadas")
    evaluate.add_argument("--queries", default=str(REPO_ROOT / "evaluation" / "queries_wikipedia_es.json"))
    evaluate.add_argument("--collection", default=WIKIPEDIA_COLLECTION)
    evaluate.add_argument("--methods", nargs="+", default=["tfidf", "bm25"])
    evaluate.add_argument("--output", default=None)
    evaluate.add_argument("--split", choices=["dev", "test"], default=None, help="subconjunto de consultas")
    evaluate.add_argument("--baseline", default="bm25", help="método de referencia para la prueba de significación")
    evaluate.add_argument(
        "--long-text",
        choices=["mean", "truncate"],
        default=None,
        help="estrategia de textos largos del codificador (experimento con índice aparte)",
    )
    evaluate.set_defaults(func=_cmd_evaluate)
    benchmark = sub.add_parser("benchmark", help="medir la latencia de búsqueda")
    benchmark.add_argument("--queries", default=str(REPO_ROOT / "evaluation" / "queries_wikipedia_es.json"))
    benchmark.add_argument("--collection", default=WIKIPEDIA_COLLECTION)
    benchmark.add_argument("--repeats", type=int, default=5)
    benchmark.add_argument(
        "--methods", nargs="+", default=["bm25", "tfidf"],
        choices=["bm25", "tfidf", "semantic", "hybrid"], help="métodos a medir",
    )
    benchmark.set_defaults(func=_cmd_benchmark)
    ocr = sub.add_parser("ocr", help="reconocer con OCR los PDF escaneados pendientes (needs_ocr)")
    ocr.add_argument("--collection", default="user", help="colección (por defecto, user)")
    ocr.set_defaults(func=_cmd_ocr)
    tessdata = sub.add_parser("tessdata", help="instalar idiomas de Tesseract en data/tessdata")
    tessdata.add_argument("--languages", nargs="+", default=["spa", "eng"])
    tessdata.add_argument("--variant", choices=["fast", "best"], default="fast")
    tessdata.set_defaults(func=_cmd_tessdata)
    miracl = sub.add_parser("miracl", help="importar MIRACL español (dev, anotado por personas) para evaluar")
    miracl.set_defaults(func=_cmd_miracl)
    embeddings = sub.add_parser("embeddings", help="cargar el modelo de embeddings y medir la codificación")
    embeddings.add_argument("--collection", default=None, help="codificar los fragmentos de esta colección")
    embeddings.add_argument("--limit", type=int, default=None, help="máximo de fragmentos a codificar")
    embeddings.set_defaults(func=_cmd_embeddings)
    semantic = sub.add_parser("semantic-index", help="construir o sincronizar el índice semántico FAISS")
    semantic.add_argument("--collection", action="append", help="colección (repetible; por defecto, todas)")
    semantic.add_argument("--rebuild", action="store_true", help="reconstruir desde cero")
    semantic.set_defaults(func=_cmd_semantic_index)
    hashpw = sub.add_parser("hash-password", help="generar el hash de una contraseña local (DOC-25)")
    hashpw.add_argument("--stdin", action="store_true", help="leer la contraseña de la entrada estándar")
    hashpw.set_defaults(func=_cmd_hash_password)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
