# Bitácora técnica

Registro por Issue de objetivo, cambios, decisiones, pruebas y resultados reales.

## DOC-02 — Esquema de Document, Chunk y metadatos persistentes

- **Issue:** #2 · **Rama:** `feature/DOC-02-document-models`
- **Objetivo:** contratos estables de documento y fragmento, persistencia local
  reproducible y separación entre original, metadatos e índices.
- **Cambios:**
  - `backend/app/config.py`: rutas `originals/`, `metadata.db`, `indexes/`
    bajo `DOCUSEARCH_DATA_DIR` (por defecto `data/`).
  - `backend/app/documents/models.py`: `Document`, `Chunk`, `ExtractionStatus`,
    `SourceType`, IDs deterministas.
  - `backend/app/documents/repository.py`: `DocumentRepository` sobre SQLite.
  - `backend/app/documents/storage.py`: `OriginalStore` con protección contra
    path traversal y escritura atómica.
  - `backend/app/search/models.py`: contrato `SearchHit`.
  - `pyproject.toml`: dependencia explícita `pydantic>=2.7,<3`.
- **Decisiones:** ver `docs/modelo-datos.md`.
- **Fuentes:** `documentacion.pdf` no estaba disponible en el repositorio ni se
  proporcionó en esta sesión; el diseño se basa en el Issue #2, `docs/` y el
  prompt de trabajo. Revisar contra el PDF cuando esté disponible.
- **Pruebas:** `python -m pytest -q` en Windows, Python 3.12.10 →
  `46 passed, 1 warning` (advertencia de deprecación de Starlette/httpx, ajena a
  este cambio). Python 3.10 y 3.11 se verifican en GitHub Actions.
- **Pendientes:** lectores PDF/DOCX/TXT (DOC-03), endpoints y validación de
  carga (DOC-04), fragmentación 200/30 (DOC-07).

## DOC-03 — Lectura de PDF, Word DOCX y TXT

- **Issue:** #3 · **Rama:** `feature/DOC-03-document-readers`
- **Objetivo:** extraer texto y metadatos de PDF digital, DOCX y TXT con errores
  controlados y metadatos utilizables por el índice y la interfaz.
- **Cambios:**
  - `backend/app/documents/readers.py`: interfaz `DocumentReader`, lectores
    `PdfReader`, `DocxReader`, `TxtReader`, `extract_document`, `build_document`.
  - `tests/fixtures/`: `muestra.pdf`, `muestra.docx`, `muestra.txt`,
    `expected.json` y `generate_fixtures.py`.
  - `tests/test_document_readers.py`: 32 pruebas nuevas.
  - `pyproject.toml`: PyMuPDF y python-docx pasan a dependencias principales.
  - `.gitattributes`: fixtures con bytes exactos.
- **Decisiones:** ver `docs/lectores.md`. Errores de contenido como estado en el
  resultado; formato no admitido como excepción. PDF sin texto → `needs_ocr`.
- **Riesgo detectado:** PyMuPDF es AGPL-3.0 (o comercial) y el repositorio no
  declara licencia. Requiere decisión del equipo.
- **Versiones locales:** PyMuPDF 1.28.2, python-docx 1.2.0.
- **Pruebas:** `python -m pytest -q` en Windows, Python 3.12.10 →
  `78 passed, 1 warning` (misma advertencia de Starlette/httpx).
- **Pendientes:** endpoints de carga con validación de tipo real y tamaño
  (DOC-04); OCR (DOC-23); Google Docs (DOC-22).

## DOC-04 — Endpoints para subir, listar y descargar documentos

- **Issue:** #4 · **Rama:** `feature/DOC-04-document-api`
- **Objetivo:** usar documentos reales vía API antes del motor de búsqueda.
- **Cambios:**
  - `backend/app/api/documents.py`: `POST /documents`, `GET /documents`,
    `GET /documents/{doc_id}`, `GET /documents/{doc_id}/download`.
  - `backend/app/documents/validation.py`: nombre seguro, extensión, tamaño,
    tipo real por firma, límite de descompresión de DOCX y rechazo de macros.
  - `backend/app/documents/service.py`: orquestación validación → extracción →
    original → metadatos, con limpieza del original si falla el registro.
  - `backend/app/config.py`: `Settings` con límites configurables por entorno.
  - `backend/app/main.py`: fábrica `create_app(settings)`; los servicios de
    datos se crean en la primera petición (importar la app no crea archivos).
  - `pyproject.toml`: `python-multipart` pasa a dependencias principales; se
    elimina el extra `documents`.
- **Decisiones:** ver `docs/api.md`. Duplicado → 409 con el `doc_id`
  existente. PDF sin texto → se acepta con `needs_ocr`. Archivos dañados o sin
  texto → 422 sin guardar nada.
- **Pruebas:** `python -m pytest -q` en Windows, Python 3.12.10 →
  `135 passed, 1 warning`. Prueba manual con `uvicorn` y `curl`: carga de PDF
  (201), consulta (200), descarga con bytes idénticos al original, `.exe`
  rechazado (415) y duplicado (409).
- **Pendientes / riesgos:** sin autenticación; el límite de tamaño no evita
  que Starlette guarde temporalmente el cuerpo multipart (usar límite en proxy);
  sin endpoint de borrado ni reindexación.

## DOC-06 — Preprocesamiento PLN léxico y semántico

- **Issue:** #6 · **Rama:** `feature/DOC-06-nlp-preprocessing` (apilada sobre DOC-04)
- **Objetivo:** separar la normalización para TF-IDF/BM25 de la destinada a Transformers.
- **Cambios:** `backend/app/nlp/normalization.py` (`clean_text`, `strip_accents`),
  `lexical.py` (`LexicalPipeline`), `semantic.py` (`prepare_semantic`);
  `tests/test_nlp_preprocessing.py` (32 pruebas); dependencia `spacy>=3.8,<3.9`
  y extra `model` con `es_core_news_sm` 3.8.0 fijado; CI instala `.[dev,model]`.
- **Decisiones:** ver `docs/preprocesamiento.md` (lista de stopwords ajustada,
  plegado de tildes conservando la ñ, fallback sin lematizar).
- **Riesgo:** `es_core_news_sm` es GPL-3.0.
- **Pruebas:** `python -m pytest -q` → `167 passed, 1 warning` (Windows, Python 3.12.10, spaCy 3.8.18).

## DOC-07 — Fragmentación 200/30

- **Issue:** #7 · **Rama:** `feature/DOC-07-chunking` (apilada sobre DOC-06)
- **Cambios:** `backend/app/nlp/chunking.py` (`ChunkingConfig`, `chunk_text`,
  `chunk_extraction`); `DocumentService` fragmenta en la carga (todo-o-nada) y
  `rechunk` regenera desde originales; `DocumentRepository.update_extra` y
  `count_chunks`; `GET /documents/{doc_id}/chunks`; `chunk_count` en la
  respuesta de carga; CLI `python -m backend.app.cli rechunk`;
  `Settings.chunk_size/chunk_overlap`; `tests/test_chunking.py` (18 pruebas).
- **Decisiones:** ver `docs/fragmentacion.md` (palabras `\S+` sobre el texto
  original; páginas por primera/última palabra; sin colas redundantes).
- **Pruebas:** `python -m pytest -q` → `185 passed, 1 warning` (Windows, Python 3.12.10).

## DOC-05 — Corpus Wikipedia en español

- **Issue:** #5 · **Rama:** `feature/DOC-05-wikipedia-corpus` (apilada sobre DOC-07)
- **Cambios:** `backend/app/corpus/wikipedia.py` (cliente con pausas y
  reintentos, conversión de wikitexto, `freeze`, `build`, estadísticas);
  `DocumentService.ingest_corpus_text`; CLI `corpus freeze|build|import|stats`;
  `corpus/wikipedia_es/topics.json` y `manifest.json` versionados;
  `data/corpus/` ignorado; dependencia `mwparserfromhell`;
  `tests/test_wikipedia_corpus.py` (9 pruebas, sin red).
- **Ejecución real (2026-11-17, UTC):** `freeze` → 275 artículos, 8 excluidos
  por < 50 palabras; `build` desde cero → 275/275 con SHA-256 idéntico;
  `import` → 275 documentos y 1978 fragmentos en ~11 s; segunda importación →
  0 nuevos (idempotente). Durante la exploración inicial la API respondió
  HTTP 429; por eso el cliente espera 1 s entre peticiones y respeta `Retry-After`.
- **Pruebas:** `python -m pytest -q` → `194 passed, 1 warning`.
- **Limitaciones:** muestreo alfabético por categoría y temas desbalanceados (ver `docs/corpus.md`).

## DOC-08 — Índice y búsqueda TF-IDF

- **Issue:** #8 · **Rama:** `feature/DOC-08-tfidf` (apilada sobre DOC-05)
- **Cambios:** `backend/app/search/lexical_corpus.py` (`TokenCache`,
  `build_lexical_corpus`), `ranking.py` (`top_k`, `validate_k`), `tfidf.py`
  (`TfidfIndex`), `engine.py` (`SearchEngine`, `make_snippet`); campo `page` en
  `SearchHit`; `DocumentRepository.collection_signature`; dependencias
  `numpy` y `scikit-learn`; `tests/conftest.py` y `tests/test_tfidf.py`
  (23 pruebas).
- **Medición real:** corpus `wikipedia_es` → 1978 fragmentos, vocabulario de
  24 384 términos; primera construcción 38,3 s; consulta con caché ~17 ms.
- **Pruebas:** `python -m pytest -q` → `217 passed, 1 warning`.

## DOC-09 — BM25 como línea base experimental

- **Issue:** #9 · **Rama:** `feature/DOC-09-bm25` (apilada sobre DOC-08)
- **Cambios:** `backend/app/search/bm25.py` (`BM25Index`), registro en el
  motor como método por defecto; `evaluation.py` (Recall@k, MRR@10, nDCG@10 a
  nivel de documento); CLI `evaluate`; `evaluation/queries_wikipedia_es.json`
  (32 consultas: 15 léxicas, 17 paráfrasis); resultados reales en
  `evaluation/results/wikipedia_es_tfidf_bm25.json`; `tests/test_bm25.py`
  (21 pruebas).
- **Resultados reales:** MRR@10 0.880 (BM25) frente a 0.828 (TF-IDF); nDCG@10
  0.890 frente a 0.856. BM25 falla P12 (Desinflación). Latencia media de unos
  72 ms por consulta con profundidad 100. Ver `docs/evaluacion.md`.
- **Limitaciones:** consultas redactadas por el asistente, pendientes de
  revisión humana; corpus pequeño y temas muy separados.
- **Pruebas:** `python -m pytest -q` → `234 passed, 1 warning`.

## DOC-10 — API de búsqueda léxica

- **Issue:** #10 · **Rama:** `feature/DOC-10-search-api` (apilada sobre DOC-09)
- **Cambios:** `backend/app/api/search.py` (`GET /search`, `GET /search/index`,
  motor único por aplicación); router registrado en `main.py`; CLI `reindex`;
  `tests/test_search_api.py` (24 pruebas).
- **Prueba manual (uvicorn):** con los 3 fixtures cargados, cada formato se
  recupera con su consulta, y el PDF con página 1–2. La primera consulta tardó
  ~1,4 s (carga de modelos) y las siguientes ~5 ms. Se detectó que `curl` en
  Git Bash envía las tildes en otra codificación (la consulta llegaba como
  `ndice`); ahora la API devuelve 422 `invalid_encoding` y la documentación
  recomienda `Invoke-RestMethod`.
- **Fallo encontrado en pruebas:** una consulta "sin resultados" contenía
  "palabra", que sí aparece en los fixtures; se corrigió la prueba.
- **Pruebas:** `python -m pytest -q` → `258 passed, 1 warning`.

## DOC-11 — Pruebas del MVP v0.1

- **Issue:** #11 · **Rama:** `feature/DOC-11-v01-tests` (apilada sobre DOC-10)
- **Cambios:** `tests/test_v01_end_to_end.py` (flujo completo, 27 cargas
  inválidas, reinicio, latencia, CLI); `benchmark_latency` y CLI `benchmark`;
  `pytest-cov` en `dev`; `docs/pruebas.md`; comandos de prueba en el README.
- **Fallo encontrado y corregido:** las consultas cortas se lematizaban mal
  (`dengue` → `denguir`, `lava` → `lavar`) porque spaCy etiqueta sin contexto.
  El pipeline léxico pasa a la **v2**, que indexa el lema y la forma
  superficial con prefijo `=`. Se añadieron pruebas de regresión y la caché de
  tokens se invalida por versión.
- **Evaluación repetida (v2):** BM25 MRR@10 0.905 y nDCG@10 0.921; TF-IDF
  0.845 y 0.878. La v1 queda como histórico en `docs/evaluacion.md`.
- **Benchmark real:** BM25 p95 de 26,9 ms y máximo de 28,0 ms; TF-IDF p95 de
  28,5 ms y máximo de 32,1 ms (32 consultas × 5); arranque de 5,1 s con caché.
- **Pruebas:** `python -m pytest -q` → `269 passed, 1 warning`; cobertura del 96 %.
