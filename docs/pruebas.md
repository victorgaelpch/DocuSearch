# Pruebas (DOC-11, DOC-17)

## v0.2: búsqueda semántica e híbrida (DOC-17)

```powershell
python -m pip install -e ".[dev,model,semantic]"
python -m pytest -q                                    # suite completa (sin descargar el modelo)
python -m pytest -q tests/test_v02_end_to_end.py       # extremo a extremo de v0.2
$env:DOCUSEARCH_TEST_SEMANTIC_MODEL = "1"
python -m pytest -q -m semantic_model                  # solo las del modelo real
python -m backend.app.cli benchmark --queries evaluation/queries_wikipedia_es_v2.json --methods bm25 tfidf semantic hybrid
```

**Resultados (ejecución real, Windows, Python 3.12.10, CPU de 16 hilos):**

- `python -m pytest -q` → **332 passed, 4 skipped**. Las 4 omitidas usan el
  modelo real; con `DOCUSEARCH_TEST_SEMANTIC_MODEL=1` pasan las 4.
- Cobertura de `backend/`: **97 %** (2503 sentencias, 80 sin cubrir).
- **CI:**
  - El job `tests` (Python 3.10–3.12) instala `faiss-cpu` sin PyTorch y
    ejecuta todas las pruebas con el codificador simulado.
  - El job `semantic-model` (Python 3.12) instala PyTorch para CPU y el extra
    `semantic`, guarda el modelo en la caché de Actions y ejecuta
    `-m semantic_model`.
  - Es opcional (`continue-on-error`) para que un corte de Hugging Face no
    bloquee los PR.

**Qué cubre `tests/test_v02_end_to_end.py`:**

- Flujo completo con `semantic` y `hybrid`: un término de la página 3 de un
  PDF se atribuye a esa página y la descarga devuelve el PDF.
- Al reiniciar, el índice FAISS se carga de disco: el codificador solo procesa
  la consulta, y los resultados y la versión coinciden.
- Sin el extra `semantic`, el flujo v0.1 sigue funcionando; `semantic` e
  `hybrid` responden 503.
- Latencia por debajo de 2 s con los tres métodos en un corpus sintético.
- `benchmark --methods semantic hybrid`.

**Rendimiento real** (`benchmark --repeats 5`, `wikipedia_es`: 275
artículos, 1978 fragmentos; 48 consultas × 5 por método; k=10):

| Método | p50 | p95 | Máximo |
| --- | --- | --- | --- |
| bm25 | 13,7 ms | 16,1 ms | 20,8 ms |
| tfidf | 15,0 ms | 17,0 ms | 18,5 ms |
| semantic | 31,6 ms | 35,7 ms | 39,9 ms |
| hybrid | 41,7 ms | 50,3 ms | 64,3 ms |

Todas las consultas quedan muy por debajo del requisito de 2 s.

| Coste | Valor |
| --- | --- |
| Arranque léxico (spaCy + índices, con caché de tokens) | 5,2 s |
| Arranque semántico (cargar el modelo e índice FAISS de disco) | 5,8 s |
| Construir el índice FAISS desde cero (DOC-13) | 113,6 s |
| Memoria residente, solo métodos léxicos | 430 MB |
| Memoria residente, con semántica e híbrida | 1279 MB (+~850 MB por PyTorch y el modelo) |

La memoria se mide con `psutil`, que forma parte del extra `dev`.

---

# Pruebas del MVP v0.1 (DOC-11)

## Comandos

```powershell
python -m pip install -e ".[dev,model]"
python -m pytest -q                                   # suite completa
python -m pytest -q --cov=backend --cov-report=term   # con cobertura
python -m pytest -q tests/test_v01_end_to_end.py      # solo extremo a extremo
python -m pytest -q -k "search or bm25"               # por palabra clave
```

Mediciones sobre el corpus real (requieren `corpus build` + `corpus import`,
ver `docs/corpus.md`):

```powershell
python -m backend.app.cli evaluate --output evaluation/results/x.json
python -m backend.app.cli benchmark --repeats 5
```

## Resultados (ejecución real, Windows, Python 3.12.10, CPU)

- `python -m pytest -q` → **269 passed**, 1 advertencia (deprecación de
  Starlette/httpx, ajena al proyecto), en unos 30–40 s.
- Cobertura de `backend/`: **96 %** (1940 sentencias, 72 sin cubrir).
- El CI ejecuta la misma suite en Python 3.10, 3.11 y 3.12 sobre Ubuntu.

## Qué se comprueba

| Área | Archivos de prueba | Casos clave |
| --- | --- | --- |
| Modelos y persistencia | `test_document_models.py`, `test_document_repository.py` | IDs estables, rutas seguras, duplicados, reindexación atómica |
| Lectores | `test_document_readers.py` | PDF, DOCX y TXT válidos; vacíos, truncados, cifrados y renombrados; PDF sin texto |
| Validación de carga y API | `test_upload_validation.py`, `test_documents_api.py` | Tipo real, tamaño, ZIP bomb, macros, path traversal, códigos 4xx |
| PLN | `test_nlp_preprocessing.py` | Acentos, signos, marcado, texto ruidoso, stopwords, lemas, regresión del etiquetado |
| Fragmentación | `test_chunking.py` | 200/30, solapamiento, offsets, páginas, determinismo, `rechunk` |
| Corpus | `test_wikipedia_corpus.py` | Conversión, filtros, reconstrucción por `revid`, separación de colecciones (sin red) |
| Búsqueda | `test_tfidf.py`, `test_bm25.py`, `test_search_api.py` | Orden, k, consultas vacías o sin resultados, fórmula BM25, métricas, `/search` |
| Extremo a extremo | `test_v01_end_to_end.py` | Flujo completo, relación resultado–documento–página, 30 archivos inválidos, reinicio, latencia, CLI |

## Criterios de DOC-11

- **Suite repetible:** usa fixtures sintéticos (`tests/fixtures/` y archivos
  generados en memoria con semillas fijas), directorios temporales por prueba
  y ninguna descarga ni documento privado.
- **Ningún archivo inválido rompe el servicio:**
  `test_no_invalid_file_breaks_the_service` sube 27 cargas inválidas o
  límite: truncados a varias longitudes, bytes aleatorios, corrupción
  aleatoria, XML roto, nombres peligrosos, etc. Ninguna devuelve 5xx; después,
  `/health`, `/search` y todas las descargas siguen funcionando.
- **Relación resultado–documento–página:**
  `test_full_flow_result_document_page_relation` coloca un término único en
  la página 3 de un PDF de 3 páginas. Comprueba que cada resultado incluye esa
  página en su rango, que el fragmento contiene el término y que la descarga
  devuelve el PDF.

## Fallos encontrados por esta suite

1. **Lematización de consultas cortas** (defecto real del pipeline de DOC-06).
   Sin contexto, spaCy etiqueta `dengue`, `lava` o `embeddings` como verbos y
   los lematiza como `denguir`, `lavar`…, así que no coincidían con los
   documentos. Corrección: pipeline léxico **v2**, que indexa el lema y la
   forma superficial (`docs/preprocesamiento.md`). Se añadió una prueba de
   regresión. Efecto medido en `docs/evaluacion.md`.
2. Algunas cargas "inválidas" de la prueba aleatoria, como los TXT truncados,
   son en realidad texto válido y se aceptan (201). Es el comportamiento
   esperado y la prueba lo admite.

## Rendimiento (RNF: menos de 2 s)

`python -m backend.app.cli benchmark --repeats 5` sobre `wikipedia_es` (275
artículos, 1978 fragmentos), con 32 consultas × 5 repeticiones por método y
los índices ya construidos:

| Método | p50 | p95 | Máximo |
| --- | --- | --- | --- |
| BM25 | 21,8 ms | 26,9 ms | 28,0 ms |
| TF-IDF | 23,9 ms | 28,5 ms | 32,1 ms |

El arranque (cargar spaCy y construir los índices con la caché de tokens ya
creada) tardó 5,1 s; sin caché, la lematización completa tardó 38,3 s
(DOC-08). La medición es del motor sin HTTP, en un único equipo. La prueba
`test_latency_under_two_seconds_on_synthetic_corpus` la repite con datos
sintéticos en cada ejecución de la suite.
