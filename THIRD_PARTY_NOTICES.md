# Avisos de terceros

DocuSearch AI se distribuye bajo `AGPL-3.0-or-later` (ver `LICENSE`). Usa
los componentes de terceros listados abajo, cada uno con su propia licencia.
Este repositorio **no incluye** el código, los binarios, los modelos ni los
datos de terceros: se instalan o descargan aparte. Las licencias se tomaron de
los metadatos de los paquetes instalados y de las fichas de los modelos y
conjuntos de datos (noviembre de 2026).

## Dependencias de Python

| Componente | Licencia | Uso |
| --- | --- | --- |
| FastAPI, Pydantic, python-docx, spaCy, mwparserfromhell, faiss-cpu, pytest, pytest-cov | MIT | API, modelos, DOCX, PLN, corpus, índice semántico, pruebas |
| Starlette, Uvicorn, NumPy, scikit-learn, lxml, httpx, psutil | BSD-3-Clause (NumPy incluye además otras permisivas) | API, cálculo, TF-IDF, DOCX, pruebas |
| python-multipart, sentence-transformers, transformers, huggingface-hub, tokenizers, safetensors, pyarrow | Apache-2.0 | cargas, embeddings, evaluación |
| PyTorch | BSD-3-Clause y otras permisivas | embeddings (extra `semantic`) |
| **PyMuPDF** | **AGPL-3.0** (o licencia comercial de Artifex) | lectura de PDF y OCR |
| Playwright para Python y navegador Chromium que descarga | Apache-2.0 (Chromium: BSD-3-Clause y otras) | solo pruebas E2E (extra `e2e`); no forma parte de la aplicación |

La interfaz web (`frontend/`) no incluye bibliotecas de terceros: HTML, CSS y
JavaScript propios, con las fuentes del sistema operativo. La página `/docs`
de FastAPI carga Swagger UI (Apache-2.0) desde jsDelivr en el navegador.

## Modelos

| Modelo | Licencia | Uso |
| --- | --- | --- |
| `es_core_news_sm` 3.8.0 (spaCy) | **GPL-3.0** | lematización (extra `model`) |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Apache-2.0 | embeddings (extra `semantic`) |
| Tesseract OCR y modelos `tessdata_fast`/`tessdata_best` (`spa`, `eng`) | Apache-2.0 | OCR (programa del sistema; modelos en `data/tessdata/`) |

## Datos

| Datos | Licencia | Uso |
| --- | --- | --- |
| Textos de Wikipedia en español (corpus `wikipedia_es`) | CC BY-SA 4.0 | corpus experimental; el repositorio solo versiona el manifiesto (títulos, `revid`, hashes) |
| MIRACL v1.0, español, split `dev` (Zhang et al., 2023) | Apache-2.0 (pasajes de Wikipedia: CC BY-SA) | evaluación; se descarga en `data/miracl/` y solo se versionan las métricas |

Quien redistribuya textos o pasajes de Wikipedia debe atribuir la fuente y
mantener la licencia CC BY-SA para esos datos.

## Compatibilidad

La AGPL-3.0 es compatible con todas las licencias permisivas listadas y con
la GPL-3.0, gracias a la sección 13 de ambas licencias. Por eso el conjunto
puede distribuirse bajo `AGPL-3.0-or-later` sin cambiar ninguna dependencia.
El análisis completo está en `docs/licencias.md`.
