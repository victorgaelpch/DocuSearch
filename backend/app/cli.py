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
    python -m backend.app.cli hash-password [--stdin] [--env-file .env]
    python -m backend.app.cli doctor
    python -m backend.app.cli demo [--queries]
    python -m backend.app.cli report [--repeats 5] [--output informe.json]

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


def _read_stdin_line() -> str:
    """Primera línea de stdin sin BOM ni fin de línea.

    Windows PowerShell 5.1 puede anteponer un BOM al canalizar texto a un
    programa (``"clave" | python …``) según ``$OutputEncoding``; sin quitarlo,
    el BOM formaría parte de la contraseña.
    """
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:  # stdin sustituido por texto (pruebas)
        line = sys.stdin.readline()
    else:
        raw = buffer.readline()
        try:
            line = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            line = raw.decode(sys.stdin.encoding or "utf-8", errors="strict")
    return line.lstrip("\ufeff").rstrip("\r\n")


def _cmd_hash_password(args: argparse.Namespace) -> int:
    """Genera el hash scrypt para DOCUSEARCH_ADMIN/USER_PASSWORD_HASH (DOC-25).

    La contraseña se pide sin eco (o se lee de stdin) y nunca se imprime.
    """
    import getpass

    from backend.app.auth.passwords import hash_password

    if args.stdin:
        password = _read_stdin_line()
    else:
        password = getpass.getpass("Contraseña (mínimo 12 caracteres): ")
        if getpass.getpass("Repita la contraseña: ") != password:
            print("Las contraseñas no coinciden.", file=sys.stderr)
            return 1
    try:
        encoded = hash_password(password)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.env_file:
        _write_env_value(Path(args.env_file), f"DOCUSEARCH_{args.role.upper()}_PASSWORD_HASH", encoded)
        print(f"Hash guardado en {args.env_file} (DOCUSEARCH_{args.role.upper()}_PASSWORD_HASH).")
    else:
        print(encoded)
    return 0


def _write_env_value(path: Path, key: str, value: str) -> None:
    """Escribe o reemplaza ``KEY=valor`` en un .env local sin tocar otras líneas."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    lines = [line for line in lines if not line.strip().startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Diagnóstico de la instalación local (DOC-34). Código 1 si falta algo esencial."""
    import importlib.util
    import platform
    import shutil
    import socket

    from backend.app.config import load_env_file

    checks: list[tuple[str, bool, str, bool]] = []  # nombre, ok, detalle, esencial

    def add(name: str, ok: bool, detail: str, essential: bool = True) -> None:
        checks.append((name, ok, detail, essential))

    version = sys.version_info
    add("Python >= 3.10", version >= (3, 10), platform.python_version())
    add("Entorno virtual", sys.prefix != sys.base_prefix, sys.prefix, essential=False)
    for module in ("fastapi", "uvicorn", "pymupdf", "docx", "spacy", "sklearn"):
        add(f"Paquete {module}", importlib.util.find_spec(module) is not None, "instalado" if importlib.util.find_spec(module) else 'falta: python -m pip install -e ".[model]"')
    model = importlib.util.find_spec("es_core_news_sm") is not None
    add("Modelo spaCy es_core_news_sm", model, "instalado" if model else 'falta: python -m pip install -e ".[model]"')
    loaded = load_env_file()
    settings = Settings.from_env()
    add("Cuenta de Administrador", bool(settings.admin_password_hash),
        "configurada" if settings.admin_password_hash else "sin hash: python -m backend.app.cli hash-password --env-file .env")
    if loaded:
        add("Archivo .env", True, f"variables cargadas: {', '.join(sorted(loaded))}", essential=False)
    try:
        settings.paths.ensure()
        probe = settings.paths.root / ".escritura"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        add("Carpeta de datos escribible", True, str(settings.paths.root))
    except OSError as exc:
        add("Carpeta de datos escribible", False, f"{settings.paths.root}: {exc}")
    from backend.app.documents.ocr import find_tessdata

    tessdata = find_tessdata()
    spa = bool(tessdata and (tessdata / "spa.traineddata").is_file())
    add("OCR (Tesseract + español)", spa, f"tessdata en {tessdata}" if spa else
        ("Tesseract sin idioma español: python -m backend.app.cli tessdata" if shutil.which("tesseract") else "no instalado: PDF escaneados quedarán como pendientes de OCR"), essential=False)
    semantic = importlib.util.find_spec("sentence_transformers") is not None and importlib.util.find_spec("faiss") is not None
    add("Búsqueda semántica (extra semantic)", semantic, "instalada" if semantic else 'opcional: python -m pip install -e ".[semantic]" (BM25 funciona sin ella)', essential=False)
    with socket.socket() as sock:
        free = sock.connect_ex(("127.0.0.1", args.port)) != 0
    add(f"Puerto {args.port} libre", free, "libre" if free else "ocupado: ¿ya hay un servidor en marcha? use --port otro", essential=False)

    width = max(len(name) for name, *_ in checks)
    for name, ok, detail, essential in checks:
        mark = "OK " if ok else ("ERR" if essential else "-- ")
        print(f"[{mark}] {name.ljust(width)}  {detail}")
    missing = [name for name, ok, _, essential in checks if essential and not ok]
    print("\nListo para iniciar." if not missing else f"\nFalta: {', '.join(missing)}.")
    return 1 if missing else 0


def _cmd_demo(args: argparse.Namespace) -> int:
    """Carga los documentos sintéticos de demo/documentos en la colección user (DOC-34)."""
    demo_dir = REPO_ROOT / "demo"
    queries = json.loads((demo_dir / "consultas.json").read_text(encoding="utf-8"))
    if args.queries:
        for group in ("lexicas", "parafrasis", "ocr"):
            print(f"\n{group}:")
            for item in queries[group]:
                print(f"  {item['consulta']!r} -> {item['documento']}")
        return 0
    service = DocumentService(Settings.from_env())
    loaded = 0
    for path in sorted((demo_dir / "documentos").iterdir()):
        if path.suffix.lower() not in {".pdf", ".docx", ".txt"}:
            continue
        try:
            result = service.ingest(path.name, path.read_bytes())
        except DuplicateDocumentError:
            print(f"  ya cargado: {path.name}")
            continue
        loaded += 1
        status = result.document.extraction_status.value
        note = " (sin OCR: instale Tesseract con español y ejecute 'cli ocr')" if status == "needs_ocr" else ""
        print(f"  cargado: {path.name} -> {result.document.doc_id}, {status}, {len(result.chunks)} fragmento(s){note}")
    print(f"\n{loaded} documento(s) nuevo(s). Pruebe en http://127.0.0.1:8000/#/buscar con:")
    for item in queries["lexicas"][:3]:
        print(f"  {item['consulta']}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    """Informe de rendimiento reproducible sobre la demostración (DOC-40)."""
    from backend.app.perf import format_report, run_report

    report = run_report(repeats=args.repeats, methods=args.methods)
    print(format_report(report))
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nInforme JSON: {args.output}")
    return 0 if report["within_2s"] else 1


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
    hashpw.add_argument("--env-file", default=None, help="guardar el hash en este archivo .env en lugar de imprimirlo")
    hashpw.add_argument("--role", choices=["admin", "user"], default="admin", help="cuenta a la que pertenece el hash")
    hashpw.set_defaults(func=_cmd_hash_password)
    doctor = sub.add_parser("doctor", help="diagnosticar la instalación local (Python, paquetes, OCR, semántica, cuenta)")
    doctor.add_argument("--port", type=int, default=8000)
    doctor.set_defaults(func=_cmd_doctor)
    demo = sub.add_parser("demo", help="cargar los documentos sintéticos de demo/documentos")
    demo.add_argument("--queries", action="store_true", help="mostrar solo las consultas de ejemplo")
    demo.set_defaults(func=_cmd_demo)
    report = sub.add_parser("report", help="informe de rendimiento reproducible (ingesta, frío y caliente, memoria)")
    report.add_argument("--repeats", type=int, default=5)
    report.add_argument("--methods", nargs="+", choices=["bm25", "tfidf", "semantic", "hybrid"], default=None)
    report.add_argument("--output", default=None)
    report.set_defaults(func=_cmd_report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
