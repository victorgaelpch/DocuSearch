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

### Contratos planeados (no implementados)

- `/documents`: cargar y consultar archivos con validaciones (DOC-04).
- `/search`: recuperar top-k con fragmento, puntuación y procedencia (DOC-10).

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
