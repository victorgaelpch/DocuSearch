# Modelo de datos: Document, Chunk y metadatos (DOC-02)

Código: `backend/app/documents/models.py`, `repository.py`, `storage.py`,
`backend/app/config.py` y `backend/app/search/models.py`.

## Separación del almacenamiento

```text
data/                      # raíz configurable con DOCUSEARCH_DATA_DIR (no versionada)
  originals/<colección>/   # archivos originales, nombrados <doc_id><ext>
  metadata.db              # SQLite: tablas documents y chunks
  indexes/                 # artefactos TF-IDF/BM25/FAISS (reconstruibles)
```

- El **original** nunca se guarda con el nombre enviado por el usuario: se usa
  `<colección>/<doc_id><ext>`. `OriginalStore.resolve` rechaza rutas absolutas,
  `..`, barras invertidas y unidades de Windows (path traversal).
- Los **metadatos** y el **texto extraído** (fragmentos) viven en SQLite.
- Los **índices** van en otro directorio y se pueden borrar y regenerar sin
  perder documentos.

## `Document`

| Campo | Tipo | Notas |
| --- | --- | --- |
| `doc_id` | `doc_` + 24 hex | `sha256("<colección>:<sha256 del contenido>")[:24]`; estable |
| `collection` | str | `user` (documentos personales) o `wikipedia_es` (corpus académico) |
| `source_type` | `upload` \| `corpus` | Procedencia |
| `title` | str | Por defecto, nombre del archivo sin extensión |
| `original_filename` | str | Sin separadores de ruta |
| `mime_type` | str | El tipo real se valida en DOC-04 |
| `size_bytes` | int ≥ 0 | |
| `sha256` | 64 hex | Hash del original; permite detectar duplicados |
| `storage_path` | ruta relativa POSIX | Referencia al original dentro de `originals/` |
| `source_uri` | str opcional | Ej. URL de Wikipedia |
| `created_at`, `updated_at` | datetime UTC | |
| `extraction_status` | `pending`, `extracted`, `empty`, `needs_ocr`, `failed` | `failed` exige `extraction_error` |
| `extraction_error` | str opcional | |
| `page_count` | int opcional | Solo cuando el formato tiene páginas (PDF) |
| `language` | str | `es` por defecto |
| `extra` | dict JSON | Metadatos adicionales del lector |

Restricción: `(collection, sha256)` es único → el mismo archivo no se duplica
en una colección, pero sí puede existir en `user` y en `wikipedia_es` por separado.

## `Chunk`

| Campo | Tipo | Notas |
| --- | --- | --- |
| `chunk_id` | `<doc_id>_c<00000>` | Estable: depende de `doc_id` y `ordinal` |
| `doc_id` | str | Documento padre (FK con borrado en cascada) |
| `ordinal` | 0–99999 | Orden dentro del documento |
| `text` | str no vacío | Texto **original** del fragmento (sin quitar stopwords) |
| `char_start`, `char_end` | int | Offsets en el texto extraído completo; `end` exclusivo |
| `page_start`, `page_end` | int ≥ 1 opcionales | Se definen juntos; `None` en DOCX/TXT |
| `word_count` | int | Calculado al crear |

El texto se guarda sin normalizar: el pipeline léxico (DOC-06) y el semántico
generan sus propias representaciones en los índices, así no se destruye el
contexto que necesita el modelo Transformer.

## Contrato de resultado: `SearchHit`

`rank`, `score`, `method` (`tfidf`, `bm25`, `semantic`), `doc_id`, `chunk_id`,
`title`, `original_filename`, `snippet`, `page_start`, `page_end`. Todos los
métodos devolverán esta misma forma; la búsqueda se implementa en DOC-08/09/10.

## Reindexación

`DocumentRepository.replace_chunks(doc_id, chunks)` borra e inserta los
fragmentos de un documento en **una sola transacción**. Si algo falla, se
conservan los fragmentos previos. Como los IDs son deterministas, reindexar con
los mismos parámetros produce los mismos `chunk_id`, y el esquema de consulta
(`SearchHit`) no cambia.

## Decisiones

- **Pydantic v2** (ya incluido por FastAPI): validación y serialización JSON que
  se reutilizará en los endpoints de DOC-04.
- **SQLite (`sqlite3` de la biblioteca estándar)**: sin servidor ni dependencias
  nuevas, funciona en Windows/CPU, transacciones ACID y archivo único. Versión de
  esquema en `PRAGMA user_version` (actual: 1); una versión desconocida produce
  `SchemaVersionError`.
- **IDs derivados del contenido** en lugar de UUID aleatorios: reproducibilidad
  y deduplicación. Consecuencia: el mismo archivo subido dos veces a `user`
  devuelve `DuplicateDocumentError` con el documento existente.

## Limitaciones conocidas

- No hay migraciones automáticas entre versiones de esquema (solo v1).
- El repositorio abre una conexión por operación: suficiente para el MVP, no
  optimizado para cargas masivas (el corpus Wikipedia de DOC-05 podría requerir
  inserciones por lote).
- `delete_document` no borra el archivo original; debe llamarse también a
  `OriginalStore.delete` (lo orquestará DOC-04).
- La validación de tipo real, tamaño y nombre de carga corresponde a DOC-04.
