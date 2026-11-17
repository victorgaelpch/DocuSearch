# DocuSearch AI

Buscador de documentos en español, diseñado para evolucionar hacia una plataforma de gestión y consulta documental con inteligencia artificial.

> **Estado:** estructura y endpoint de salud ([DOC-01](https://github.com/victorgaelpch/DocuSearch/issues/1)); modelos `Document`/`Chunk` y persistencia SQLite de metadatos ([DOC-02](https://github.com/victorgaelpch/DocuSearch/issues/2), ver `docs/modelo-datos.md`); extracción de texto de PDF digital, DOCX y TXT ([DOC-03](https://github.com/victorgaelpch/DocuSearch/issues/3), ver `docs/lectores.md`); API para cargar, listar, consultar y descargar documentos ([DOC-04](https://github.com/victorgaelpch/DocuSearch/issues/4), ver `docs/api.md`). Preprocesamiento léxico y semántico en español ([DOC-06](https://github.com/victorgaelpch/DocuSearch/issues/6), ver `docs/preprocesamiento.md`); fragmentación 200/30 con procedencia de página ([DOC-07](https://github.com/victorgaelpch/DocuSearch/issues/7), ver `docs/fragmentacion.md`); corpus experimental de Wikipedia en español con revisiones fijadas ([DOC-05](https://github.com/victorgaelpch/DocuSearch/issues/5), ver `docs/corpus.md`). La búsqueda (DOC-08 a DOC-10) **todavía no está implementada**.

## Requisitos

- Python 3.10 o superior (recomendado: 3.11 o 3.12).
- Git; GitHub CLI (`gh`) para automatizar el Pull Request.
- No se requiere GPU.

## Instalación (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,model]"   # model: es_core_news_sm 3.8.0 para lematizar
```

Si solo tienes otra versión compatible de Python, reemplaza `py -3.11` por `python`.

## Ejecutar backend

```powershell
python -m uvicorn backend.app.main:app --reload
```

- Estado del servicio: http://127.0.0.1:8000/health
- Documentos: `POST /documents`, `GET /documents`, `GET /documents/{doc_id}`, `GET /documents/{doc_id}/download`, `GET /documents/{doc_id}/chunks` (ver `docs/api.md`)
- Documentación automática: http://127.0.0.1:8000/docs

## Datos locales

Por defecto se usa `data/` (no versionado): `originals/`, `metadata.db` e `indexes/`. Para otra ubicación:

```powershell
$env:DOCUSEARCH_DATA_DIR = "D:\docusearch-data"
$env:DOCUSEARCH_MAX_UPLOAD_MB = "20"   # tamaño máximo de carga
```

La API no tiene autenticación todavía: úsala solo en local.

## Pruebas

```powershell
python -m pytest -q
```

## Módulos

| Ruta | Responsabilidad |
| --- | --- |
| `backend/app/documents/` | Modelos, repositorio SQLite, almacén de originales (DOC-02) y lectores PDF/DOCX/TXT (DOC-03) |
| `backend/app/nlp/` | Limpieza, pipelines léxico y semántico (DOC-06); fragmentación (DOC-07) |
| `backend/app/search/` | Índices y ranking de búsqueda (DOC-08/09) |
| `backend/app/api/` | Endpoints de documentos (DOC-04); búsqueda (DOC-10) |
| `backend/app/corpus/` | Corpus experimental de Wikipedia (DOC-05) |
| `corpus/` | Configuración y manifiesto versionados del corpus |
| `frontend/` | Interfaz web en una etapa posterior |
| `tests/` | Pruebas automatizadas |
| `docs/` | Diseño y puesta en marcha |
| `data/` | Archivos locales no versionados |

## Roadmap de la fase v0.1

1. Crear estructura y configuración del entorno — **DOC-01**.
2. Definir `Document`, `Chunk` y metadatos — **DOC-02**.
3. Incorporar lectura de PDF digital, DOCX y TXT — **DOC-03**.
4. Añadir carga de documentos vía FastAPI — **DOC-04**.
5. Procesamiento, fragmentación, TF-IDF/BM25, búsquedas y pruebas — **DOC-05 a DOC-11**.

La etapa posterior incorporará embeddings multilingües y FAISS para búsqueda semántica. El sistema se diseñará para poder ejecutar los componentes principales sin GPU.

## Seguridad y datos

No subas documentos personales, PDFs de usuarios, índices, bases de datos ni secretos al repositorio. `.gitignore` excluye los directorios de trabajo locales y los archivos `.env`. Revisa también `docs/arquitectura.md`.
