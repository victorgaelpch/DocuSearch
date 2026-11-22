# API de documentos y búsqueda (DOC-04, DOC-10)

Código: `backend/app/api/documents.py`, `backend/app/documents/service.py`,
`backend/app/documents/validation.py`. La documentación interactiva está en
`http://127.0.0.1:8000/docs` (Swagger) con el servidor en marcha.

## Endpoints

> **DOC-25:** las rutas de documentos y `GET /search?collection=user` requieren sesión; las mutaciones, rol Administrador y cabecera `X-CSRF-Token`. Ver `docs/autenticacion.md`.

| Método | Ruta | Descripción | Respuestas |
| --- | --- | --- | --- |
| `POST` | `/documents` | Carga multipart (campo `file`) de un `.pdf`, `.docx` o `.txt` | 201, 400, 409, 413, 415, 422 |
| `POST` | `/documents/import` | Importa un Google Doc **público** por enlace (JSON `{"url": "…"}`, DOC-22) | 201, 403, 404, 409, 413, 415, 422, 502, 504 |
| `GET` | `/documents?limit=50&offset=0` | Lista paginada (`limit` 1–200) | 200, 422 |
| `GET` | `/documents/{doc_id}` | Metadatos de un documento | 200, 404, 422 |
| `GET` | `/search` | Búsqueda BM25, TF-IDF, semántica o híbrida (DOC-10, DOC-14, DOC-15) | 200, 422, 503 |
| `GET` | `/search/index` | Versión y parámetros de los índices | 200, 422 |
| `GET` | `/documents/{doc_id}/chunks` | Fragmentos con offsets, páginas y configuración (DOC-07) | 200, 404, 422 |
| `GET` | `/documents/{doc_id}/download` | Original como adjunto (`Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`) | 200, 404, 422 |

Ejemplo con PowerShell:

```powershell
curl.exe -F "file=@C:\ruta\informe.pdf" http://127.0.0.1:8000/documents
curl.exe http://127.0.0.1:8000/documents
```

## Importar Google Docs públicos (DOC-22)

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/documents/import `
  -ContentType "application/json" -Body '{"url": "https://docs.google.com/document/d/<ID>/edit"}'
```

- Funciona con documentos compartidos como **"cualquier persona con el
  enlace"**. Se exportan a DOCX (`/export?format=docx`) sin credenciales y se
  procesan con el lector DOCX.
- La respuesta es la misma que la de `POST /documents`, con
  `source_type: "google_docs"`, `source_uri` (enlace canónico) y
  `metadata.google_doc_id`.
- Volver a importar el mismo contenido devuelve 409; si el documento cambió,
  se crea uno nuevo (el contenido tiene otro hash).
- **Errores:**

| HTTP | `code` | Causa |
| --- | --- | --- |
| 422 | `invalid_url` | No es `https://docs.google.com/document/d/<ID>…` |
| 403 | `not_public` | Documento privado: Google redirige al inicio de sesión o no devuelve un DOCX |
| 404 | `not_found` | El documento no existe |
| 413 | `file_too_large` | El DOCX exportado supera `DOCUSEARCH_MAX_UPLOAD_MB` |
| 502 / 504 | `remote_error` / `remote_timeout` | Fallo de red o Google no responde (30 s) |

- **Seguridad:**
  - La URL de descarga se construye a partir del ID validado; nunca se usa la
    URL del usuario.
  - Solo se siguen redirecciones HTTPS a `docs.google.com` o
    `*.googleusercontent.com`.
  - El tamaño se limita mientras se lee.
- **Verificado con Google real:**
  - La plantilla pública de documentos de diseño de Chromium se importó en
    1,15 s (981 palabras, 6 fragmentos).
  - Un documento restringido devolvió 403 `not_public`.
  - Un ID inexistente devolvió 404 `not_found`.
- **Documentos privados:** requieren OAuth con la cuenta del usuario y no
  están implementados. Mientras tanto, se pueden descargar como `.docx` y
  subir con `POST /documents`.

## Búsqueda (DOC-10, DOC-14)

`GET /search?q=...&method=bm25&k=10&collection=user`

| Parámetro | Valores | Por defecto |
| --- | --- | --- |
| `q` | texto, entre 1 y 500 caracteres, en UTF-8 | obligatorio |
| `method` | `bm25`, `tfidf`, `semantic`, `hybrid` | `bm25` |
| `k` | entero entre 1 y 100 | `10` |
| `collection` | `user` (documentos cargados), `wikipedia_es` (corpus) | `user` |

Respuesta:

```json
{
  "query": "índice invertido", "query_tokens": ["indice", "invertido"],
  "method": "bm25", "k": 10, "collection": "user",
  "index_version": "…", "total": 1, "took_ms": 4.9,
  "results": [{
    "rank": 1, "score": 2.003206, "method": "bm25",
    "doc_id": "doc_…", "chunk_id": "doc_…_c00000",
    "title": "Informe de prueba DocuSearch", "original_filename": "muestra.pdf",
    "snippet": "…", "page": 1, "page_start": 1, "page_end": 2,
    "download_url": "/documents/doc_…/download"
  }]
}
```

- Para la misma `index_version`, el orden siempre es el mismo (puntuación y,
  en empate, `chunk_id`). La versión cambia al cargar o refragmentar.
- Una consulta vacía o solo con espacios devuelve 422 `empty_query`. Una
  consulta con caracteres que no son UTF-8 devuelve 422 `invalid_encoding`.
  `k`, `method` o `collection` fuera de rango devuelven el 422 estándar de
  FastAPI, que indica el campo afectado.
- Una consulta sin coincidencias, o formada solo por stopwords, devuelve 200
  con `total: 0`.
- `GET /search/index?collection=user` devuelve la `index_version`, el número
  de fragmentos y los parámetros de BM25, TF-IDF y del pipeline léxico.
- **`method=semantic` (DOC-14)** busca por significado con embeddings y FAISS
  (`docs/indice-semantico.md`). La respuesta tiene el mismo formato; la
  puntuación es el coseno y `query_tokens` va vacío. Solo se devuelven
  fragmentos con coseno mayor que 0, igual que los léxicos solo devuelven
  puntuación positiva. Requiere el extra `semantic`; sin él responde 503
  `semantic_unavailable` y los métodos léxicos siguen funcionando.
- **`method=hybrid` (DOC-15)** fusiona BM25 y la búsqueda semántica con
  Reciprocal Rank Fusion (k=60); `score` es la puntuación RRF. Ver
  `docs/busqueda.md`. Tiene los mismos requisitos y errores que `semantic`.
- La primera búsqueda semántica sobre una colección carga el modelo (~9 s) y
  codifica los fragmentos que aún no estén en el índice. Con un corpus grande
  puede tardar minutos (`wikipedia_es`: 114 s); para evitarlo, construye el
  índice antes con `python -m backend.app.cli semantic-index`. Los documentos
  subidos después se añaden de forma incremental en la siguiente búsqueda
  semántica.
- La primera consulta de cada método tras arrancar el servidor tarda alrededor
  de 1,4 s, porque carga spaCy y scikit-learn y construye el índice. Las
  siguientes tardan unos milisegundos (medido en local con 3 documentos).

Ejemplos en PowerShell (`Invoke-RestMethod` envía UTF-8 correctamente):

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/search?q=enfermedad transmitida por mosquitos&collection=wikipedia_es"
Invoke-RestMethod "http://127.0.0.1:8000/search?q=índice invertido&method=tfidf&k=5"
Invoke-RestMethod "http://127.0.0.1:8000/search?q=infección que contagian los zancudos&method=semantic"
```

> En Git Bash para Windows, `curl --data-urlencode` puede enviar las tildes en
> otra codificación; la API lo rechaza con `invalid_encoding`.

### Reindexación

```powershell
python -m backend.app.cli reindex                    # todas las colecciones
python -m backend.app.cli reindex --collection user
python -m backend.app.cli reindex --semantic          # también el índice FAISS
```

Vuelve a extraer y fragmentar todos los documentos desde sus originales con la
configuración actual, y reconstruye los índices y la caché de tokens. Un
servidor en marcha detecta el cambio y reconstruye sus índices en memoria en
la siguiente consulta. Se ofrece como **comando local**, no como endpoint,
porque la API todavía no tiene autenticación.

## Respuesta de carga (201)

Incluye los metadatos del documento (`doc_id`, `title`, `original_filename`,
`mime_type`, `size_bytes`, `sha256`, `created_at`, `updated_at`,
`extraction_status`, `extraction_error`, `page_count`, `language`, `metadata`,
`download_url`) más `word_count`, `chunk_count` y `warnings` de la extracción. **La ruta
interna del original no se expone.**

## Errores

Todos los errores propios usan el formato:

```json
{"error": {"code": "duplicate_document", "message": "el documento ya fue cargado", "doc_id": "doc_…"}}
```

| Código HTTP | `code` | Causa |
| --- | --- | --- |
| 400 | `empty_file`, `invalid_filename` | Archivo de 0 bytes o nombre inválido |
| 409 | `duplicate_document` | Mismo contenido ya cargado (incluye el `doc_id` existente) |
| 413 | `file_too_large`, `docx_too_large`, `docx_too_complex` | Supera el máximo o el DOCX descomprimido es excesivo |
| 415 | `unsupported_format`, `content_mismatch`, `macros_not_allowed` | Extensión no admitida, contenido que no corresponde a la extensión o DOCX con macros |
| 422 | `corrupt_file`, `no_text` | Archivo dañado o sin texto extraíble |
| 404 | `not_found`, `original_missing` | Documento inexistente o original ausente en disco |
| 503 | `semantic_unavailable` | `method=semantic` o `hybrid` sin el extra `semantic` o sin poder cargar el modelo |

Los errores de validación de FastAPI (campo `file` ausente, `doc_id` con
formato inválido, `limit` fuera de rango) mantienen el formato estándar
`{"detail": [...]}` con código 422.

## Validaciones de seguridad

1. **Nombre:** se toma solo el nombre final (sin rutas), se normaliza a NFC, se
   eliminan caracteres de control y de formato (p. ej. U+202E), se rechazan
   nombres reservados de Windows y se limita a 255 caracteres. El original se
   guarda como `originals/user/<doc_id><ext>`, nunca con el nombre del cliente.
2. **Extensión:** solo `.pdf`, `.docx`, `.txt`.
3. **Tamaño:** máximo configurable (`DOCUSEARCH_MAX_UPLOAD_MB`, 20 MB por
   defecto). Se revisa `Content-Length` y los bytes leídos.
4. **Tipo real por firma de bytes** (el `Content-Type` del cliente se ignora):
   PDF con `%PDF-`; DOCX como ZIP con `[Content_Types].xml` y
   `word/document.xml`, sin `vbaProject.bin` (macros); TXT sin bytes nulos ni
   firmas de ejecutables, imágenes o archivos comprimidos.
5. **ZIP bomb:** el DOCX se rechaza si el tamaño descomprimido declarado supera
   `DOCUSEARCH_MAX_DOCX_UNCOMPRESSED_MB` (200 MB por defecto) o si tiene más de
   2000 entradas.
6. **Extracción:** si el lector devuelve `failed` o `empty`, el archivo se
   rechaza y **no se guarda**. Los PDF sin texto se aceptan con `needs_ocr`.
7. Los archivos nunca se ejecutan; se sirven como adjunto con `nosniff`.

## Configuración

| Variable | Por defecto | Uso |
| --- | --- | --- |
| `DOCUSEARCH_DATA_DIR` | `data/` | Raíz de originales, `metadata.db` e índices |
| `DOCUSEARCH_MAX_UPLOAD_MB` | `20` | Tamaño máximo de carga |
| `DOCUSEARCH_MAX_DOCX_UNCOMPRESSED_MB` | `200` | Límite de descompresión de DOCX |
| `DOCUSEARCH_CHUNK_SIZE` / `DOCUSEARCH_CHUNK_OVERLAP` | `200` / `30` | Fragmentación (DOC-07) |

## Limitaciones

- Starlette guarda el cuerpo multipart en un archivo temporal **antes** de que
  el endpoint compruebe el tamaño, cuando el cliente no envía `Content-Length`.
  En producción conviene limitar también el cuerpo en el proxy inverso
  (p. ej. `client_max_body_size` en nginx).
- Sin autenticación ni separación por usuario: todos los documentos están en la
  colección `user`. No exponer la API a internet en este estado.
- El texto se persiste como fragmentos (DOC-07); `rechunk` lo regenera desde los originales.
- No hay endpoint de borrado ni de reindexación (fuera del alcance de DOC-04).
- El tipo de PDF se valida por cabecera; los PDF malformados se detectan al
  extraer (422 `corrupt_file`).
