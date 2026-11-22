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


## Pruebas de la web en navegador real (DOC-26)

`tests/e2e/` arranca un servidor uvicorn real en un puerto libre, con datos y
cuentas temporales, y lo recorre con Playwright (Chromium). Se omiten salvo
que se defina `DOCUSEARCH_TEST_BROWSER=1`.

```powershell
python -m pip install -e ".[dev,model,e2e]"
python -m playwright install chromium          # o $env:DOCUSEARCH_E2E_CHANNEL = "chrome"
$env:DOCUSEARCH_TEST_BROWSER = "1"
python -m pytest -q tests/e2e                  # capturas en e2e-artifacts/
```

`tests/test_web.py` comprueba sin navegador que la interfaz se sirve en el
mismo origen con los tipos MIME correctos, que no hay recursos externos ni
`innerHTML`, y la estructura accesible de `index.html`.


## Batería E2E y CI bloqueante (DOC-33)

| Archivo | Cubre |
| --- | --- |
| `tests/e2e/test_web_shell.py` | Carga sin errores de JS, enlace de salto, login con errores, cookie inaccesible desde JS, logout, ruta inexistente, servidor caído, menú móvil, contraste ≥ 4.5:1, etiquetas |
| `tests/e2e/test_web_documents.py` | Carga PDF/DOCX/TXT, duplicado, inválidos, PDF escaneado, filtros, rol Usuario, redirección anónima |
| `tests/e2e/test_web_viewer.py` | Fragmento resaltado y navegación, XSS en el texto, vista PDF en su página, DOCX sin vista PDF, escaneado sin OCR, documento inexistente |
| `tests/e2e/test_web_search.py` | BM25 con posición, puntuación y página, híbrida comparada con BM25, 503, consulta vacía, corpus público; paráfrasis con el modelo real (solo en `semantic-model`) |
| `tests/e2e/test_web_admin_documents.py` | Editar, eliminar con confirmación, rol Usuario sin acciones |
| `tests/e2e/test_web_indexes.py` | Reindexar y sincronizar desde el panel, acciones semánticas sin modelo, acceso solo Administrador |
| `tests/e2e/test_web_security.py` | Todas las vistas bajo la CSP sin violaciones, título malicioso como texto, CSRF real desde otro origen |
| `tests/e2e/test_web_journey.py` | Recorrido completo PDF/DOCX/TXT → búsqueda BM25 e híbrida → fragmento de origen → edición → reindexación → eliminación → cierre de sesión |
| `tests/e2e/test_web_keyboard.py` | Sesión, búsqueda y apertura del resultado solo con teclado; foco visible; diálogo con foco en Cancelar y Escape |
| `tests/e2e/test_web_capturas.py` | Capturas de la demostración para la documentación (`docs/capturas/`, DOC-35) |

Todos los datos son sintéticos (`tests/fixtures/`, `tests/synthetic.py`) y las
contraseñas de prueba se generan al azar en cada ejecución.

### Checks de GitHub Actions

| Check | Qué ejecuta | ¿Bloquea? |
| --- | --- | --- |
| `tests (3.10)`, `tests (3.11)`, `tests (3.12)` | `python -m pytest -q` (Tesseract español incluido) | Sí |
| `web-e2e` | `python -m pytest -q tests/e2e` en Chromium de Playwright, con capturas como artefacto `web-e2e-evidencias` | Sí |
| `GitGuardian Security Checks` | Detección de secretos | Sí |
| `windows-install` | Instalación limpia con los scripts de PowerShell, demostración y recorrido HTTP en Windows (DOC-34) | Exigido por el script de fusión |
| `docker-local` | Imagen y Compose: healthcheck, solo `127.0.0.1`, recorrido HTTP y persistencia en el volumen (DOC-41) | Exigido por el script de fusión |
| `semantic-model` | Pruebas con el modelo real (API y paráfrasis en el navegador) | No (`continue-on-error`): depende de Hugging Face; se exige cuando un PR cambia el motor semántico |

**Protección de rama:** la cuenta con la que se automatizó esta entrega no
tiene permisos de administración del repositorio, así que no puede activar la
protección de `main`. Se recomienda que el propietario la active en
*Settings → Branches* exigiendo los checks bloqueantes de la tabla. Mientras
tanto, el script de fusión usado en la entrega comprueba esos checks antes de
cada merge.

### Resultados de la entrega v1.0.0 (DOC-35)

| Batería | Resultado |
| --- | --- |
| `python -m pytest -q` (Linux, Python 3.13, sin extras `semantic`/`eval`) | 524 aprobadas, 8 omitidas (modelo real, red, pyarrow) |
| `tests/e2e` (Chrome del sistema) | 38 aprobadas, 1 omitida (paráfrasis con el modelo real) |
| CI `semantic-model` | 5 pruebas con el modelo real, incluida la paráfrasis desde el navegador |
| CI `windows-install` | Instalación limpia, cuenta, demostración y búsqueda BM25 por HTTP en Windows (798,7 ms en frío) |
