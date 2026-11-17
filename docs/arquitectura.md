# Arquitectura inicial de DocuSearch AI

## Objetivo de esta entrega

Implementar la estructura modular y un endpoint de salud, sin mezclar responsabilidades ni simular funciones aún no desarrolladas.

## Flujo previsto

```text
Usuario -> Frontend -> FastAPI -> Documentos / Búsqueda
                                   |           |
                                Lectores    Ranking
                                   |           |
                              Metadatos    Índices
                                   |           |
                               Chunks  -> BM25 / TF-IDF -> Embeddings / FAISS
```

### Etapa DOC-01

- El backend arranca con `python -m uvicorn backend.app.main:app --reload`.
- `/health` retorna un JSON estable para pruebas y CI.
- Las rutas y funciones de extracción no están implementadas en esta etapa.

### Contratos implementados (DOC-02)

- `Document`, `Chunk` y `SearchHit`, con persistencia SQLite y almacén de originales. Detalle en `docs/modelo-datos.md`.
- Lectores PDF (PyMuPDF), DOCX (python-docx) y TXT con `extract_document` (DOC-03). Detalle en `docs/lectores.md`.
- `/documents`: carga, listado, consulta y descarga con validación de nombre, tamaño y tipo real (DOC-04). Detalle en `docs/api.md`.
- Pipelines léxico (spaCy `es_core_news_sm`) y semántico separados, con limpieza común (DOC-06). Detalle en `docs/preprocesamiento.md`.
- Embeddings con `paraphrase-multilingual-MiniLM-L12-v2` en CPU, como dependencia opcional (extra `semantic`) y por ventanas de ≤128 tokens (DOC-12). Detalle en `docs/embeddings.md`.
- Fragmentación 200/30 con offsets y páginas, integrada en la carga y regenerable con `python -m backend.app.cli rechunk` (DOC-07). Detalle en `docs/fragmentacion.md`.
- Corpus `wikipedia_es` (275 artículos, revisiones fijadas) en una colección separada de `user` (DOC-05). Detalle en `docs/corpus.md`.
- `SearchEngine` con índice TF-IDF en memoria, caché de tokens en `data/indexes/` y reconstrucción automática al cambiar la colección (DOC-08). Detalle en `docs/busqueda.md`.
- BM25 (k1=1.5, b=0.75) como método por defecto y evaluación con Recall@k/MRR/nDCG@10 (DOC-09). Detalle en `docs/evaluacion.md`.
- `GET /search` y `GET /search/index` sobre `SearchEngine`; reindexación con `python -m backend.app.cli reindex` (DOC-10). Detalle en `docs/api.md`. Capas: `api/documents.py` (HTTP) → `documents/service.py` (casos de uso) → `validation.py`, `readers.py`, `storage.py`, `repository.py`.

### Contratos planeados (no implementados)


### Prioridades

1. Leer archivos PDF con texto, `.docx` y `.txt` al inicio del MVP (DOC-03).
2. Preservar relación entre resultados, fragmentos y documento/página.
3. Mantener los pipelines léxico y semántico desacoplados.
4. Preparar código y pruebas ejecutables sin GPU.

### Precauciones

- No versionar documentos privados o subidos por usuarios.
- Validar tamaño, extensión, tipo real y errores de contenido antes de indexar (DOC-04).
- Los PDF escaneados necesitan OCR; no deben tratarse como PDF con texto nativo.
- Los archivos de Google Docs nativos requerirán exportación o integración autenticada aparte.
