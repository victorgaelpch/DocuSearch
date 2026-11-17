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
