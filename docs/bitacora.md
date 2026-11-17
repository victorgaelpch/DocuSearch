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
