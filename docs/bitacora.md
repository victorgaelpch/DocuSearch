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

## DOC-12 — Servicio de embeddings multilingüe en CPU

- **Issue:** #23 · **Rama:** `feature/DOC-12-embeddings`
- **Cambios:** `backend/app/nlp/embeddings.py` (`SentenceTransformerEncoder`
  con carga perezosa y revisión fijada, `split_windows`, `HashingEncoder`
  para pruebas, `get_encoder`); extra `semantic` (`sentence-transformers`
  6.x); CLI `embeddings`; marca de pytest `semantic_model`;
  `tests/test_embeddings.py`; `docs/embeddings.md`.
- **Hallazgo:** el modelo admite 128 tokens y el 96 % de los fragmentos de
  `wikipedia_es` los supera (mediana de 304). Truncando, el modelo vería el
  43 % del texto. Se codifica por ventanas de ≤126 tokens y se promedia
  ponderando por tokens. La estrategia se eligió por cobertura, sin mirar
  métricas de recuperación; su comparación queda para DOC-16.
- **Mediciones reales:** 1978 fragmentos en 105 s en CPU (18,8/s); consulta
  p95 de 18,4 ms; modelo de ~458 MB en la caché local (fuera del repositorio).
- **Pruebas:** `python -m pytest -q` → `285 passed, 3 skipped` (las 3 omitidas
  usan el modelo real; con `DOCUSEARCH_TEST_SEMANTIC_MODEL=1` pasan las 19 de
  `tests/test_embeddings.py`). Cobertura total del 97 %; `embeddings.py` al 100 %.

## DOC-13 — Índice FAISS persistente y versionado

- **Issue:** #24 · **Rama:** `feature/DOC-13-faiss-index`
- **Cambios:** `backend/app/search/semantic_index.py` (`SemanticIndex`,
  `SemanticIndexManager`, `SyncReport`); `faiss-cpu` en el extra
  `semantic`; CLI `semantic-index`; `tests/test_semantic_index.py`;
  `docs/indice-semantico.md`.
- **Decisiones:**
  - `IndexFlatIP` (coseno exacto) porque con ~2000 fragmentos FAISS tarda
    0,2 ms y no hay que aceptar la pérdida de precisión de un índice
    aproximado.
  - Serialización desde Python, para admitir rutas con tildes en Windows,
    con SHA-256 en `meta.json`.
  - Sincronización por `chunk_id` y hash del texto: solo se codifica lo
    nuevo o cambiado.
  - Al subir un documento no se codifica en la misma petición; se añade en
    la siguiente sincronización.
- **Mediciones reales (`wikipedia_es`):** construcción en 113,6 s; carga del
  índice en 5,3 ms; búsqueda con k=100 en p95 de 16,2 ms; 3 MB en disco.
- **CI:** instala `faiss-cpu` (sin PyTorch) para ejecutar las pruebas del
  índice con el codificador simulado.
- **Pruebas:** `python -m pytest -q` → `303 passed, 3 skipped` (las 3 omitidas
  usan el modelo real); cobertura total del 97 %, `semantic_index.py` al 97 %.

## DOC-14 — Búsqueda semántica en el motor y en GET /search

- **Issue:** #25 · **Rama:** `feature/DOC-14-semantic-search`
- **Cambios:**
  - `SearchEngine` admite `method=semantic` con el gestor FAISS creado al
    primer uso (`encoder_factory` para inyectar el codificador).
  - `GET /search` acepta `semantic`; responde 503 `semantic_unavailable` sin
    el extra.
  - `create_app(encoder_factory=...)` para las pruebas.
  - `reindex --semantic`; `/search/index` informa del índice semántico sin
    construirlo.
  - `tests/test_semantic_search.py`.
- **Decisiones:**
  - Mismo formato de respuesta que BM25 (puntuación = coseno, `query_tokens`
    vacío).
  - Solo coseno > 0, como el criterio de los métodos léxicos; no se fijó un
    umbral mayor para no ajustarlo con las consultas de evaluación.
- **Mediciones reales (`wikipedia_es`):** semántica con p95 de 44,4 ms frente
  a 16,7 ms de BM25; primera búsqueda tras arrancar en 9,1 s (carga del
  modelo).
- **Modelo real:** *"infección que contagian los zancudos"* recupera el
  texto del dengue en primera posición, mientras que BM25 devuelve 0
  resultados (prueba opcional `semantic_model`).
- **Pruebas:** `python -m pytest -q` → `312 passed, 4 skipped` (las omitidas
  usan el modelo real; con `DOCUSEARCH_TEST_SEMANTIC_MODEL=1` también pasan).

## DOC-15 — Búsqueda híbrida BM25 + semántica

- **Issue:** #26 · **Rama:** `feature/DOC-15-hybrid-search` (apilada sobre DOC-14)
- **Cambios:**
  - `backend/app/search/hybrid.py` (`reciprocal_rank_fusion`, `RRF_K=60`,
    100 candidatos por método);
  - `method=hybrid` en el motor y en `GET /search`;
  - `DocumentRepository.get_chunks_by_ids`;
  - `tests/test_hybrid_search.py`.
- **Decisiones:**
  - RRF porque solo usa posiciones y no requiere normalizar puntuaciones ni
    elegir pesos.
  - k=60 del artículo original, fijado antes de evaluar.
- **Fallo propio corregido:** una prueba esperaba que un identificador
  repetido desplazara las posiciones siguientes; la implementación (y el
  sentido de "posición") no lo hace, y se corrigió la prueba.
- **Optimización medida:** la búsqueda leía de SQLite uno a uno los 100
  candidatos semánticos (híbrida: p50 de 101 ms). Con una sola consulta, p50
  de 42,2 ms y p95 de 55,7 ms; la semántica pasa de 37,1 a 32,8 ms de p50.
- **Pruebas:** `python -m pytest -q` → `321 passed, 4 skipped`.

## DOC-16 — Evaluación v0.2: léxica vs semántica vs híbrida

- **Issue:** #27 (sigue abierto: falta la revisión humana de las consultas)
  · **Rama:** `feature/DOC-16-evaluation-v02` (apilada sobre DOC-15)
- **Cambios:**
  - `evaluation/queries_wikipedia_es_v2.json` con 48 consultas nuevas (16 de
    desarrollo y 32 de prueba), confirmado en un commit propio antes de
    evaluar;
  - `--split`, `paired_permutation_test`, `compare_methods`;
  - CLI `evaluate --split --baseline --long-text`;
  - resultados en `evaluation/results/`;
  - `tests/test_evaluation_v02.py`.
- **Decisión con desarrollo:** ventanas frente a truncado: MRR@10 de 0,617
  frente a 0,565 (p=0,50). Se mantienen las ventanas.
- **Resultados de prueba (MRR@10):** BM25 0,840; híbrida 0,852 (p=0,85);
  semántica 0,777 (p=0,31); TF-IDF 0,754 (p=0,014).
- **Conclusión:** la semántica no supera a BM25 en este corpus, ni en las
  paráfrasis; la híbrida empata. BM25 sigue por defecto. Se documentan el
  análisis de errores y las hipótesis.
- **Pruebas:** `python -m pytest -q` → `326 passed, 4 skipped`.

## DOC-17 — Pruebas y rendimiento de v0.2

- **Issue:** #28 · **Rama:** `feature/DOC-17-v02-tests` (apilada sobre DOC-16)
- **Cambios:**
  - `tests/test_v02_end_to_end.py`;
  - `benchmark --methods` con carga semántica y memoria (`psutil` en `dev`);
  - job de CI `semantic-model` (PyTorch CPU, caché del modelo, opcional);
  - `.hf-cache/` en `.gitignore`;
  - `docs/pruebas.md`.
- **Rendimiento real (`wikipedia_es`, 48 consultas × 5):** p95 de 16,1 ms
  (BM25), 17,0 ms (TF-IDF), 35,7 ms (semántica) y 50,3 ms (híbrida).
  Memoria: 430 MB solo léxica y 1279 MB con semántica.
- **Pruebas:** `python -m pytest -q` → `332 passed, 4 skipped`; las 4 del
  modelo real pasan en local. Cobertura del 97 %.

## DOC-18 — Análisis de licencias (decisión pendiente del equipo)

- **Issue:** #29 (sigue abierto: la decisión es del equipo)
  · **Rama:** `feature/DOC-18-license-analysis` (apilada sobre DOC-17)
- **Cambios:** `docs/licencias.md` con el inventario de licencias tomado de
  los metadatos instalados, el conflicto (PyMuPDF AGPL-3.0 y
  `es_core_news_sm` GPL-3.0) y cuatro opciones con su coste técnico. No se
  añade `LICENSE` ni se cambia ninguna dependencia.

## DOC-23 — OCR para PDF escaneados

- **Issue:** #31 · **Rama:** `feature/DOC-23-ocr` (apilada sobre DOC-18)
- **Cambios:**
  - `backend/app/documents/ocr.py` (Tesseract vía PyMuPDF, detección de
    `tessdata`, idiomas disponibles con aviso, límite de páginas);
  - `PdfReader` reconoce solo las páginas sin texto y conserva su número;
  - `DocumentService.process_pending_ocr` y CLI `ocr`;
  - Tesseract en el CI;
  - `tests/test_ocr.py` (9 pruebas, 3 con Tesseract real).
- **Entorno:** Tesseract 5.4.0 ya estaba instalado en el equipo, pero solo
  con `eng`. No se descargó `spa.traineddata`: queda como paso del usuario.
- **Medición real:** 0,27 s por página; similitud de caracteres de 0,96–0,99
  y del 74–91 % de palabras exactas en español usando el modelo `eng`. Los
  errores son sobre todo tildes, que el pipeline léxico ya ignora.
- **Pruebas:** `python -m pytest -q` → `341 passed, 4 skipped`; cobertura del 97 % (`ocr.py` al 97 %).

## DOC-23 (continuación) — Idioma español para el OCR

- **Issue:** #31 (cerrado; mejora posterior) · **Rama:** `feature/DOC-23-spanish-ocr`
- **Cambios:**
  - `backend/app/documents/tessdata.py` y CLI `tessdata`: descargan
    `spa`/`eng` de `tesseract-ocr/tessdata_{fast,best}` fijados a un commit,
    con SHA-256 verificado, en `data/tessdata/`;
  - `find_tessdata` prefiere esa carpeta;
  - 5 pruebas nuevas.
- **Medición real** (4 páginas en español, palabras exactas): `eng` del
  sistema 73,9 %, `spa+eng` fast 98,1 % y best 98,9 %. Con escaneo difícil,
  72,6 %, 96,2 % y 97,1 %. Fast tarda 0,32 s por página frente a 0,69 s de
  best. Se eligió fast por defecto.
- **Error real observado:** `montaña y` → `montañay` a final de línea.
- **Incidente evitado:** al preparar el commit, Git incluía los modelos
  descargados porque `.gitignore` no cubría `data/tessdata/`. Se retiraron
  antes de confirmar nada y `.gitignore` pasa a ignorar todo `data/` salvo
  `data/README.md`.
- **Pruebas:** `python -m pytest -q` → `346 passed, 4 skipped`.

## DOC-22 — Importar Google Docs públicos por enlace

- **Issue:** #30 (queda abierta la parte de documentos privados con OAuth)
  · **Rama:** `feature/DOC-22-google-docs-import` (apilada sobre la mejora
  del OCR en español)
- **Cambios:**
  - `backend/app/documents/google_docs.py`: validación de la URL, export a
    DOCX, redirecciones seguras, límites, nombre del archivo;
  - `SourceType.GOOGLE_DOCS`;
  - `DocumentService.ingest_google_doc`;
  - `POST /documents/import`;
  - `source_type` y `source_uri` en las respuestas;
  - `tests/test_google_docs_import.py` (30 pruebas, una con red opcional).
- **Verificación real:**
  - plantilla pública de Chromium → 201 en 1,15 s, 981 palabras, 6
    fragmentos;
  - documento restringido → 403 `not_public`;
  - ID inexistente → 404 `not_found`.
- **Sin credenciales:** no se usa ni se guarda ningún token.
- **Pruebas:** `python -m pytest -q` → `375 passed, 5 skipped` (la omitida nueva necesita red).

## DOC-16 (cierre) — Evaluación con anotación humana: MIRACL español

- **Issue:** #27 · **Rama:** `feature/DOC-16-miracl-eval` (apilada sobre DOC-22)
- **Decisión del usuario:** en vez de una revisión manual de las consultas
  propias, el criterio de anotación humana se cumple con un conjunto público
  anotado por personas.
- **Cambios:**
  - `backend/app/corpus/miracl.py` y CLI `miracl`: descargan el parquet de
    MIRACL-es dev (2,6 MB, revisión y SHA-256 fijados) e importan los 6410
    pasajes juzgados como colección `miracl_es`;
  - extra `eval` (`pyarrow`);
  - `tests/test_miracl.py`;
  - resultados en `evaluation/results/miracl_es_dev.json`.
- **Resultados (648 consultas, nDCG@10):** híbrida 0,752, BM25 0,709,
  semántica 0,695, TF-IDF 0,660. La híbrida supera a BM25 en nDCG@10
  (p<0,0001) y MRR@10 (+0,037, p=0,0018); la semántica sola empata.
- **Recomendación:** `hybrid` con el extra `semantic`; `bm25` sigue por
  defecto en la API.
- **Tiempos:** importación 3,5 min; índice semántico 4,2 min; evaluación
  total 14 min.
- **Pruebas:** `python -m pytest -q` → `381 passed, 5 skipped`.

## DOC-18 (cierre) — Licencia AGPL-3.0-or-later

- **Issue:** #29 · **Rama:** `feature/DOC-18-license` (apilada sobre DOC-16 MIRACL)
- **Decisión:** el usuario delegó la elección ("escoge la mejor a tu
  criterio"). Se elige `AGPL-3.0-or-later`:
  - es compatible con PyMuPDF (AGPL-3.0) y con `es_core_news_sm` (GPL-3.0);
  - no requiere cambios técnicos ni empeora la calidad;
  - no tiene coste;
  - encaja con un proyecto académico público.
- **Cambios:**
  - `LICENSE` con el texto oficial de gnu.org (SHA-256 `0d96a4ff…abcb0`);
  - `pyproject.toml`: `license`, `license-files`; `setuptools>=77` para el
    formato SPDX de PEP 639;
  - `THIRD_PARTY_NOTICES.md`;
  - sección de licencia en el README;
  - `docs/licencias.md` con la decisión y su motivo.
- **Verificación:** el paquete instalado declara `License-Expression: AGPL-3.0-or-later` y los dos archivos de licencia; `python -m pytest -q` → `381 passed, 5 skipped`.

## DOC-24 — Auditoría de integración y contratos para la entrega v1.0

- **Issue:** #44 · **Rama:** `feature/DOC-24-auditoria-contratos`
- **Punto de partida:** `main` en `840eaaa` (merge del PR #40), CI verde;
  `python -m pytest -q` → `379 passed, 7 skipped` (Linux, Python 3.13).
  Los 18 Issues del backlog v1.0 ya existían en GitHub: DOC-24…DOC-41 son
  los Issues #44…#61 (no se volvieron a crear).
- **Auditoría:** la API cubre ingesta, OCR, Google Docs públicos, TF-IDF,
  BM25, semántica, híbrida y evaluación. Faltan autenticación, interfaz web,
  edición/eliminación, panel de índices, OAuth para Google Docs privados y
  RAG.
- **Cambios:**
  - `docs/adr/0001-entrega-web-v1.md`: modo local monousuario, roles,
    sesión/CSRF, colecciones públicas y privadas, contrato HTTP v1.0, tareas
    de reindexación.
  - `docs/trazabilidad.md`: matriz RF01–RF08 / RNF01–RNF07 con evidencia y
    pendientes.
  - `docs/arquitectura.md` y README: estado exacto (sin autenticación; OAuth
    pendiente).
  - `tests/test_traceability.py`: la matriz cubre los 15 requisitos.
- **Fuentes:** `documentacion.pdf` no estuvo disponible; las descripciones de
  RF/RNF se infieren del backlog y están marcadas para verificar.
- **Pruebas:** ver PR.

## DOC-25 — Autenticación local segura y permisos de Usuario/Administrador

- **Issue:** #45 · **Rama:** `feature/DOC-25-autenticacion-local`
- **Objetivo:** impedir el acceso anónimo a documentos privados y a las
  operaciones de administración, sin servicios externos.
- **Cambios:**
  - `backend/app/auth/`: hash scrypt (biblioteca estándar), sesiones en
    memoria con caducidad por inactividad y absoluta, límite de intentos por
    IP, dependencias `require_user` / `require_admin` /
    `require_admin_mutation` con CSRF por cabecera y comprobación de origen.
  - `backend/app/api/auth.py`: `POST /auth/login`, `POST /auth/logout`,
    `GET /auth/me`. `backend/app/api/errors.py`: formato de error común.
  - Documentos: lectura con sesión; carga e importación solo Administrador +
    CSRF. `GET /search` y `/search/index` exigen sesión para `collection=user`;
    los corpus públicos siguen siendo anónimos.
  - CLI `hash-password` (sin eco; `--stdin` para scripts).
  - `.env.example` sin secretos, `docs/autenticacion.md`.
  - Pruebas: `tests/auth_helpers.py` genera contraseñas aleatorias por sesión
    de pruebas e inicia sesión de verdad; las pruebas anteriores usan ese
    cliente en lugar de desactivar la protección. `tests/test_auth.py` (29).
- **Decisiones:** sin hash configurado no hay cuenta (no existe
  administrador por defecto). Un hash mal formado detiene el arranque.
  Modo local monousuario: no se declara soporte multiusuario.
- **Pruebas:** `python -m pytest -q` → `409 passed, 7 skipped` (Linux,
  Python 3.13).
- **Pendiente para DOC-32:** el cuerpo multipart se lee antes de comprobar la
  sesión (FastAPI resuelve el formulario junto con las dependencias); se
  añadirá un límite previo para peticiones anónimas.

## DOC-25 (corrección) — Falso positivo de GitGuardian

- **Issue:** #45 (ya cerrado) · **Rama:** `feature/DOC-25-gitguardian-falso-positivo`
- **Hallazgo:** el check *GitGuardian Security Checks* del PR #63 marcó
  "Generic Password" en `tests/auth_helpers.py` (líneas con
  `ADMIN_PASSWORD = "adm-" + secrets.token_urlsafe(18)`). Ese check no estaba
  entre las puertas obligatorias del ayudante de merge y el PR se fusionó.
- **Análisis:** falso positivo; los valores se generan al azar en cada
  ejecución de pytest y no existen fuera de ella. No hay credencial que
  revocar ni historial que reescribir.
- **Cambios:** la credencial de prueba se genera en una función sin literal
  de cadena; desde ahora el merge exige también *GitGuardian Security
  Checks* en verde.
- **Acción del propietario:** marcar los incidentes 40852052 y 40852053 como
  falso positivo en el panel de GitGuardian (no hay acceso desde esta sesión).
## DOC-26 — Frontend responsive y accesible integrado en FastAPI

- **Issue:** #46 · **Rama:** `feature/DOC-26-frontend-base`
- **Objetivo:** convertir `frontend/` en una aplicación real servida en el
  mismo origen, sin Node en ejecución ni recursos externos.
- **Cambios:**
  - `backend/app/web.py`: `GET /` y `/assets/*`; tipos MIME fijados para
    `.js`/`.css`/`.svg` (en Windows el registro puede devolver `text/plain`
    para `.js` y bloquear los módulos ES). `/docs` y `/openapi.json` intactos.
  - `frontend/`: `index.html`, `assets/css/app.css`, módulos `dom.js`
    (construcción segura sin `innerHTML`), `api.js` (cookie de sesión, CSRF
    en memoria, errores uniformes, aviso de servidor caído y de sesión
    expirada), `router.js` (rutas por hash, foco accesible), vistas
    Inicio, Iniciar sesión y Ayuda. Solo se listan secciones implementadas.
  - Diseño: papel de archivo frío, tinta pizarra, azul de sello y resaltador
    amarillo reservado al fragmento encontrado; fuentes del sistema
    (Palatino/Segoe UI); barra lateral en escritorio y menú en móvil.
  - Pruebas: `tests/test_web.py` (12) y `tests/e2e/` (8, Playwright) con
    servidor real; extra `e2e` en `pyproject.toml`.
- **Fallo encontrado por las pruebas E2E:** en la carga inicial el foco se
  llevaba al título y el primer Tab se saltaba el enlace "Saltar al
  contenido". Ahora solo se mueve el foco en los cambios de vista.
- **Pruebas:** `python -m pytest -q` → `428 passed, 8 skipped`;
  `DOCUSEARCH_TEST_BROWSER=1 python -m pytest -q tests/e2e` → `8 passed`
  (Chrome 1xx del sistema, Linux). Windows no verificado en esta sesión.

## DOC-27 — Interfaz de carga, listado y filtrado de documentos

- **Issue:** #47 · **Rama:** `feature/DOC-27-carga-listado-documentos`
- **Cambios:**
  - `GET /documents`: filtros en el servidor `q` (título o nombre, búsqueda
    literal con `LIKE … ESCAPE`), `format` y `status` repetibles, y `order`
    (`oldest` por defecto, compatible; `newest` para la web). `total` cuenta
    los documentos filtrados. `DocumentRepository.filter_documents`.
  - Vista `#/documentos`: carga múltiple con selector o arrastrar y soltar,
    procesamiento archivo por archivo con su resultado real (estado,
    palabras, fragmentos, avisos, `doc_id`), mensajes para 409 (con el
    identificador existente), 413, 415, 422, sesión expirada y red; la
    selección se conserva si algo falla. Importación de Google Docs públicos.
    Tabla paginada con formato, tamaño, fecha, estado y detalle (doc_id,
    SHA-256, páginas, procedencia, fragmentación, avisos, descarga). Filtros
    en la URL. El rol Usuario ve el listado sin formularios de carga.
  - Sin porcentajes simulados: cada archivo muestra "Procesando…" hasta que el
    servidor responde.
  - `tests/synthetic.py`: generador de PDF escaneado compartido con
    `test_ocr.py`.
- **Fallos encontrados por las pruebas E2E y corregidos:**
  - el enlace "Saltar al contenido" (`#main`) era interpretado como ruta y
    mostraba "Esta página no existe"; el enrutador ignora anclas que no
    empiezan por `#/`;
  - "undefined palabras" en la fragmentación del detalle (clave
    `chunk_size`), "(Word (DOCX))" y "1 fragmentos".
- **Pruebas:** `python -m pytest -q` → `433 passed, 8 skipped`; E2E
  (`DOCUSEARCH_TEST_BROWSER=1`, Chrome) → `14 passed`.
