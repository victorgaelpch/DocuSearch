# Trazabilidad de requisitos RF01–RF08 / RNF01–RNF07

> **Origen de las descripciones.** `documentacion.pdf` (avance académico UAEM,
> 2026-B) no está en el repositorio ni estuvo disponible al redactar esta
> matriz. Las descripciones se **infieren** del backlog v1.0 (qué Issue cita
> qué requisito) y de los requisitos académicos explícitos del encargo. Antes
> de la entrega, contrastar cada fila con el PDF y corregir el texto si
> difiere; la evidencia técnica no depende de esa redacción.

Estados: **Cumple** (probado y reproducible), **Parcial** (existe pero falta
una parte), **Pendiente** (no implementado), **Fuera de alcance**.

Se actualiza en cada Issue de la entrega v1.0. Última revisión: DOC-35 (entrega v1.0.0).

## Requisitos funcionales

| ID | Descripción (inferida) | Estado | Evidencia | Falta |
| --- | --- | --- | --- | --- |
| RF01 | Consultas en lenguaje natural en español | Cumple | `GET /search` (DOC-10), pipeline léxico spaCy `es_core_news_sm` (DOC-06), buscador web `#/buscar` (DOC-29); `tests/test_search_api.py`, `tests/e2e/test_web_search.py` | — |
| RF02 | La consulta se procesa con el mismo modelo/pipeline que los documentos | Cumple (API) | `SearchEngine` usa el mismo `LexicalPipeline` y el mismo `Encoder` (`paraphrase-multilingual-MiniLM-L12-v2`) para documentos y consulta; huella del codificador en `meta.json` (DOC-12/13) | — |
| RF03 | Recuperación por similitud: FAISS con producto interno sobre vectores normalizados, BM25/TF-IDF léxicos e híbrida | Cumple (API) | `IndexFlatIP` (`docs/indice-semantico.md`), `tests/test_semantic_index.py`, `tests/test_hybrid_search.py` | — (selector de método en la web, DOC-29) |
| RF04 | Top-k configurable, 10 por defecto | Cumple | `DEFAULT_TOP_K = 10` en `search/ranking.py`; `k` 1–100 en `/search` y en la web (predeterminado 10, DOC-29) | — |
| RF05 | Cada resultado muestra título, fragmento, puntuación y origen (documento/página) | Cumple | `SearchHit` con `title`, `snippet`, `score`, `doc_id`, `chunk_id`, `page`; el visor abre `#/documentos/{doc_id}?chunk={chunk_id}` con el fragmento resaltado y la página (DOC-28, `tests/e2e/test_web_viewer.py`) | — |
| RF06 | Vista completa del documento y gestión del documento por el usuario | Cumple | Metadatos, fragmentos y descarga por API (DOC-04/07), protegidos por sesión y rol (DOC-25, `tests/test_auth.py`); visor web con metadatos, texto completo y PDF (DOC-28); edición y eliminación consistentes (DOC-30, `tests/test_document_admin.py`) | — |
| RF07 | Carga e indexación de documentos (PDF, DOCX, TXT, OCR, Google Docs públicos) | Parcial | `POST /documents`, `POST /documents/import`, CLI `reindex`/`semantic-index`/`ocr`; carga, importación y listado desde la web con resultado real de extracción (DOC-27, `tests/e2e/test_web_documents.py`); panel de índices y tareas con estado real (DOC-31, `tests/test_index_jobs.py`) | Google Docs privados (DOC-37, OAuth) |
| RF08 | Comparación de la búsqueda semántica/híbrida con la línea base BM25 | Cumple (evaluación) | `docs/evaluacion.md`, `evaluation/results/miracl_es_dev.json` (648 consultas MIRACL-es dev, subconjunto de pasajes juzgados) | Comparación lado a lado con BM25 en la web (DOC-29); panel de métricas (DOC-36) |

## Requisitos no funcionales

| ID | Descripción (inferida) | Estado | Evidencia | Falta |
| --- | --- | --- | --- | --- |
| RNF01 | Búsqueda sobre índice caliente en menos de 2 s | Cumple (API) | `docs/pruebas.md`: p95 BM25 26,9 ms, híbrida 50,3 ms (corpus de prueba, CPU) | Medición desde la web (DOC-40). No aplica a generación RAG |
| RNF02 | Calidad medida con Recall@k, MRR@10 y nDCG@10 | Cumple | `backend/app/search/evaluation.py`, `docs/evaluacion.md` | Panel de evaluación (DOC-36) |
| RNF03 | Arquitectura modular y mantenible; índices reconstruibles | Cumple | Capas `api/ → documents/service → repository/storage`, `search/` independiente; índices regenerables desde originales | — (borrado con compensación y purga de índices, DOC-30) |
| RNF04 | Usabilidad: interfaz en español, accesible y clara | Cumple | Interfaz web en `/` con navegación por teclado, enlace de salto, foco gestionado, contraste AA y diseño responsive, verificada en Chrome real (`tests/e2e/test_web_shell.py`, DOC-26); vistas de documentos, visor, buscador e índices (DOC-27 a DOC-31); flujo completo con teclado y check bloqueante `web-e2e` (DOC-33) | Sin evaluación con usuarios reales ni lector de pantalla físico |
| RNF05 | Ejecución en CPU, Python ≥ 3.10, sin GPU (Windows) | Cumple | CI 3.10–3.12; extra `semantic` con PyTorch CPU; scripts PowerShell e instalación limpia verificada en `windows-latest` (DOC-34, `docs/instalacion-windows.md`) | Sin verificación en un Windows de escritorio; OCR y semántica no verificados en Windows |
| RNF06 | Seguridad y privacidad de los documentos | Cumple (uso local) | Validación de cargas, path traversal y SSRF en importación (DOC-04/22); sesión `HttpOnly`, CSRF, roles y límite de intentos (DOC-25); CSP y cabeceras, rechazo previo al cuerpo, purga al borrar, pruebas adversariales (DOC-32, `docs/seguridad.md`, `tests/test_security.py`) | Exposición en red: HTTPS y pasos de `docs/seguridad.md`; sin auditoría externa |
| RNF07 | Reproducibilidad: pruebas automatizadas, CI y resultados versionados | Cumple | CI GitHub Actions (Python 3.10–3.12 y `web-e2e` en Chromium, DOC-33), `evaluation/results/`, revisiones de corpus fijadas | — (instalación limpia en Windows en CI, DOC-34) |


## Issues y Pull Requests de la entrega v1.0

| ID | Issue | Alcance | PR | Requisitos |
| --- | --- | --- | --- | --- |
| DOC-24 | [#44](https://github.com/victorgaelpch/DocuSearch/issues/44) | Auditoría y contratos (ADR, esta matriz) | [#62](https://github.com/victorgaelpch/DocuSearch/pull/62) | RF01–RF08, RNF03, RNF06 |
| DOC-25 | [#45](https://github.com/victorgaelpch/DocuSearch/issues/45) | Autenticación local y roles | [#63](https://github.com/victorgaelpch/DocuSearch/pull/63), [#64](https://github.com/victorgaelpch/DocuSearch/pull/64) | RF06, RNF04, RNF05 |
| DOC-26 | [#46](https://github.com/victorgaelpch/DocuSearch/issues/46) | Frontend accesible en el mismo origen | [#65](https://github.com/victorgaelpch/DocuSearch/pull/65) | RNF04, RNF05, RNF06 |
| DOC-27 | [#47](https://github.com/victorgaelpch/DocuSearch/issues/47) | Carga, listado y filtros | [#66](https://github.com/victorgaelpch/DocuSearch/pull/66) | RF06, RF07, RNF04 |
| DOC-28 | [#48](https://github.com/victorgaelpch/DocuSearch/issues/48) | Visor con fragmento y página | [#67](https://github.com/victorgaelpch/DocuSearch/pull/67) | RF05, RF06, RNF04 |
| DOC-29 | [#49](https://github.com/victorgaelpch/DocuSearch/issues/49) | Buscador web con 4 métodos | [#68](https://github.com/victorgaelpch/DocuSearch/pull/68) | RF01–RF05, RF08, RNF01, RNF04 |
| DOC-30 | [#50](https://github.com/victorgaelpch/DocuSearch/issues/50) | Editar y eliminar con índices coherentes | [#69](https://github.com/victorgaelpch/DocuSearch/pull/69) | RF06, RF07, RNF03 |
| DOC-31 | [#51](https://github.com/victorgaelpch/DocuSearch/issues/51) | Panel de índices y tareas | [#70](https://github.com/victorgaelpch/DocuSearch/pull/70) | RF07, RNF01, RNF03, RNF05 |
| DOC-32 | [#52](https://github.com/victorgaelpch/DocuSearch/issues/52) | Endurecimiento de seguridad | [#71](https://github.com/victorgaelpch/DocuSearch/pull/71) | RNF04, RNF06 |
| DOC-33 | [#53](https://github.com/victorgaelpch/DocuSearch/issues/53) | E2E y CI bloqueante | [#72](https://github.com/victorgaelpch/DocuSearch/pull/72) | RF01–RF08, RNF04, RNF06, RNF07 |
| DOC-34 | [#54](https://github.com/victorgaelpch/DocuSearch/issues/54) | Instalación en Windows y demostración | [#73](https://github.com/victorgaelpch/DocuSearch/pull/73) | RNF04–RNF07 |
| DOC-35 | [#55](https://github.com/victorgaelpch/DocuSearch/issues/55) | Entrega final v1.0 | este PR | RF01–RF08, RNF01–RNF07 |

Versiones anteriores (v0.1–v0.2, DOC-01 a DOC-23): Issues #1–#31 y PR #12–#43; ver `docs/bitacora.md`.

## Limitaciones declaradas

- **MIRACL:** las cifras (nDCG@10 híbrida 0,752 frente a BM25 0,709) se
  midieron sobre las 648 consultas de MIRACL-es *dev* y **solo el subconjunto
  de pasajes juzgados** (6410), no sobre el corpus MIRACL completo. No son
  cifras oficiales del benchmark.
- **Modo local monousuario** (DOC-25): no es multiusuario y no debe
  exponerse fuera de `127.0.0.1` sin HTTPS y el endurecimiento de DOC-32.
- **Google Docs privados** requieren OAuth con un proyecto del propietario
  (DOC-37); hoy solo se importan documentos públicos.
- **RAG** no existe (DOC-38/39, P1). No hay evaluación RAG.
- **Fuente de los requisitos:** sin `documentacion.pdf`, la redacción de
  RF/RNF es inferida (ver la nota inicial).
