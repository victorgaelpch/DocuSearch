# Licencias del proyecto y de sus dependencias (DOC-18)

> **Estado: pendiente de decisión del equipo.** Este documento reúne los
> datos y las opciones para decidir; no elige la licencia ni es asesoría
> legal. El repositorio todavía **no declara licencia**. Hasta que exista un
> archivo `LICENSE`, nadie fuera del equipo tiene permiso para reutilizar el
> código.

## Inventario

Licencias tomadas de los metadatos de los paquetes instalados (Windows,
Python 3.12.10, noviembre de 2026).

| Paquete | Versión | Licencia | Uso | Tipo |
| --- | --- | --- | --- | --- |
| fastapi | 0.163.1 | MIT | API | permisiva |
| starlette | 1.10.0 | BSD-3-Clause | API (dependencia de FastAPI) | permisiva |
| pydantic | 2.14.3 | MIT | modelos | permisiva |
| uvicorn | 0.54.0 | BSD-3-Clause | servidor | permisiva |
| python-multipart | 0.0.34 | Apache-2.0 | cargas | permisiva |
| **PyMuPDF** | 1.28.2 | **AGPL-3.0** o licencia comercial de Artifex | lector PDF (DOC-03) | **copyleft fuerte (red)** |
| python-docx | 1.2.0 | MIT | lector DOCX | permisiva |
| lxml | 6.1.3 | BSD-3-Clause | DOCX (dependencia) | permisiva |
| spacy | 3.8.18 | MIT | PLN | permisiva |
| **es_core_news_sm** | 3.8.0 | **GPL-3.0** | lematización (extra `model`) | **copyleft** |
| mwparserfromhell | 0.7.2 | MIT | corpus Wikipedia | permisiva |
| numpy | 2.5.5 | BSD-3-Clause (y otras permisivas) | cálculo | permisiva |
| scikit-learn | 1.9.1 | BSD-3-Clause | TF-IDF | permisiva |
| sentence-transformers | 6.3.0 | Apache-2.0 | embeddings (extra `semantic`) | permisiva |
| torch | 2.15.0 | Apache-2.0, BSD y otras permisivas | embeddings | permisiva |
| transformers | 5.23.0 | Apache-2.0 | embeddings | permisiva |
| huggingface-hub, tokenizers, safetensors | 2.4.0 / 0.23.3 / 0.8.0 | Apache-2.0 | embeddings | permisiva |
| faiss-cpu | 1.16.0 | MIT | índice semántico | permisiva |
| paraphrase-multilingual-MiniLM-L12-v2 | rev. `e8f8c211` | Apache-2.0 (ficha del modelo) | modelo de embeddings | permisiva |
| pytest, pytest-cov, httpx, psutil | — | MIT / MIT / BSD-3 / BSD-3 | solo desarrollo | permisiva |

**Datos:**

- Los textos de Wikipedia están bajo **CC BY-SA 4.0**. El repositorio solo
  versiona el manifiesto (títulos, `revid`, hashes), no los textos.
- Si alguna vez se distribuyen los textos o los fragmentos, hay que atribuir
  la fuente y mantener la misma licencia para esos datos.

## Dónde está el conflicto

1. **PyMuPDF (AGPL-3.0).**
   - Si el proyecto se distribuye, o se ofrece como servicio a usuarios a
     través de la red con PyMuPDF dentro, la AGPL obliga a publicar el código
     fuente completo bajo AGPL-3.0.
   - La alternativa es comprar la licencia comercial de Artifex.
   - Es la dependencia más restrictiva.
2. **`es_core_news_sm` (GPL-3.0).**
   - Es un modelo, es decir, datos cargados en tiempo de ejecución, no código
     enlazado. Si un modelo así obliga al código que lo usa a ser GPL es una
     cuestión **discutida**.
   - Si el proyecto ya fuera AGPL-3.0, no habría conflicto, porque la AGPL-3.0
     y la GPL-3.0 son compatibles entre sí.
   - Es opcional: sin el extra `model`, el pipeline funciona sin lematizar y
     lo indica con `"lemmatizer": null`.
3. Todo lo demás es permisivo (MIT, BSD, Apache-2.0) y compatible con
   cualquiera de las opciones.

## Opciones

| Opción | Qué implica | Coste técnico | Riesgo |
| --- | --- | --- | --- |
| **A. Licenciar el proyecto como AGPL-3.0** | Compatible con PyMuPDF y con el modelo GPL. Quien ofrezca el servicio a terceros debe publicar su código. | Ninguno: añadir `LICENSE` y cabeceras. | Bajo. Impide reutilizarlo en productos cerrados. |
| **B. Licencia permisiva (MIT o Apache-2.0) sustituyendo dependencias** | Cambiar PyMuPDF por `pypdf` (BSD) o `pdfminer.six` (MIT). Cambiar o quitar `es_core_news_sm`: lematizar por reglas (*lookups* de spaCy) o con otra herramienta de licencia verificada. | Medio: reescribir `PdfReader` (páginas, PDF cifrados y sin texto) y medir de nuevo la calidad léxica (DOC-16), porque cambia la lematización. | Medio: `pypdf` y `pdfminer` extraen peor algunos PDF; habría que comprobarlo con los fixtures. |
| **C. Licencia permisiva con licencia comercial de PyMuPDF** | Pagar a Artifex; el modelo GPL sigue en discusión (punto 2). | Ninguno. | Coste económico; no resuelve del todo el modelo. |
| **D. Uso solo académico e interno, sin distribuir** | Mientras no se distribuya ni se ofrezca a terceros, la AGPL no exige publicar nada. | Ninguno. | Hay que decidirlo antes de publicar o desplegar. Sin `LICENSE`, nadie más puede reutilizar el código. |

Como dato para decidir:

- Si el proyecto es académico y de código abierto, la opción **A** es la más
  simple y no cambia nada técnico.
- Si se quiere permitir su uso en productos cerrados, la opción **B** es la
  única sin coste económico, pero exige trabajo y una nueva evaluación.

## Qué queda por hacer cuando el equipo decida

- [ ] Elegir la opción y registrarla en `docs/bitacora.md`.
- [ ] Añadir `LICENSE` y el campo `license` de `pyproject.toml`.
- [ ] Opción B: abrir Issues para sustituir el lector PDF y la lematización,
      y repetir DOC-16.
- [ ] Añadir un archivo de avisos de terceros (`THIRD_PARTY_NOTICES`) si se
      distribuyen binarios o imágenes de contenedor.
