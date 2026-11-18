# Índice semántico FAISS (DOC-13)

Código: `backend/app/search/semantic_index.py`. Pruebas:
`tests/test_semantic_index.py`. Requiere el extra `semantic`, que incluye
`faiss-cpu` 1.x con licencia MIT (ver `docs/embeddings.md`).

Guarda los embeddings de los fragmentos (DOC-12) para buscarlos por
similitud. Desde DOC-14 lo usa `GET /search?method=semantic` (ver `docs/api.md`).

## Diseño

- **Tipo de índice:** `faiss.IndexFlatIP`. Como los vectores están
  normalizados, el producto interno es el coseno. Es una búsqueda **exacta**
  (fuerza bruta):
  - con 1978 fragmentos tarda 0,2 ms y ocupa 3 MB;
  - no hace falta entrenar el índice ni aceptar la pérdida de precisión de los
    índices aproximados;
  - si algún día hay cientos de miles de fragmentos, se podrá cambiar a
    `IndexHNSWFlat` o `IndexIVFFlat`.
- **Un índice por colección:** `user` y `wikipedia_es` nunca se mezclan. El
  nombre de la colección se valida (`[a-z0-9_]+`) antes de usarlo como
  carpeta.
- **Ubicación:** `data/indexes/semantic/<colección>/`, excluida por
  `.gitignore`. Nunca se versiona.
  - `index.faiss`: el índice, serializado con `faiss.serialize_index`. Se
    escribe desde Python para admitir rutas con tildes en Windows.
  - `meta.json`: formato, configuración y huella del codificador, el
    `chunk_id` y el hash del texto de cada posición, y el SHA-256 de
    `index.faiss`.
  - Ambos se escriben de forma atómica (archivo temporal + `os.replace`).

## Cuándo se reconstruye

Al cargar se comprueba todo. Si algo no cuadra, el índice se descarta y se
reconstruye; nunca se usa un índice dudoso:

| Motivo (`reason`) | Causa |
| --- | --- |
| `missing` | No existe todavía |
| `unreadable` | `meta.json` no es JSON válido |
| `format` | Formato de archivo de otra versión |
| `encoder_changed` | Cambió el modelo, la revisión, la estrategia de textos largos o el pipeline semántico |
| `checksum` | `index.faiss` no coincide con su SHA-256, por ejemplo por una escritura a medias |
| `corrupt` | FAISS no puede leer el archivo |
| `mismatch` | El número de vectores o la dimensión no coinciden con `meta.json` |

## Sincronización incremental

`SemanticIndex.sync(repository)` compara el índice con los fragmentos
actuales de la colección por `chunk_id` y hash del texto:

- **Nuevos o con texto cambiado:** se codifican y se añaden. Es lo único
  costoso.
- **Borrados o cambiados:** se quitan. Los vectores que se conservan se
  recuperan del propio índice (`reconstruct_n`), sin volver a codificarlos.
- **Sin cambios:** no se codifica nada.

`SemanticIndexManager` mantiene un índice por colección. Solo sincroniza
cuando cambia `repository.collection_signature`, la misma firma que usa la
búsqueda léxica.

Al subir un documento **no** se codifica en ese momento: hacerlo exigiría el
modelo y tardaría ~0,05 s por fragmento dentro de la petición. Sus
fragmentos se añaden en la siguiente sincronización: en la próxima búsqueda
semántica (DOC-14) o con el comando de abajo.

Los documentos sin texto (`needs_ocr`, `empty`) no tienen fragmentos, así que
nunca entran en el índice.

## Búsqueda

`search(query, k)` y `search_vector(vector, k)` devuelven
`(chunk_id, coseno)` ordenados de mayor a menor. Los empates (a 6 decimales)
se deshacen por `chunk_id` para que el orden sea reproducible. Una consulta
vacía, que da el vector cero, o una colección vacía devuelven `[]`. A
diferencia de BM25, no se descartan las puntuaciones bajas: decidir si se
corta por umbral es parte de DOC-14.

## Comando

```powershell
python -m backend.app.cli semantic-index                              # todas las colecciones
python -m backend.app.cli semantic-index --collection wikipedia_es    # una (repetible)
python -m backend.app.cli semantic-index --collection user --rebuild  # desde cero
```

Muestra, por colección, el total de vectores, los añadidos, borrados y
conservados, el motivo, el tiempo y la versión del índice.

## Resultados medidos (Windows, CPU, `wikipedia_es`: 275 artículos, 1978 fragmentos)

| Operación | Tiempo |
| --- | --- |
| Construcción desde cero (codificar con ventanas + indexar) | 113,6 s |
| Carga del modelo desde la caché | 8,6 s |
| Carga del índice desde disco | 5,3 ms |
| Sincronización sin cambios (leer fragmentos y comparar hashes) | 205 ms |
| Búsqueda con k=100 (codificar la consulta + FAISS), 32 consultas × 5 | p50 de 14,1 ms, p95 de 16,2 ms, máximo de 21,1 ms |
| Solo FAISS, k=100 | 0,2 ms |

Tamaño en disco: `index.faiss` ocupa 3,0 MB (1978 × 384 × 4 bytes) y
`meta.json`, 0,2 MB.

Casi todo el tiempo se va en el modelo (cargarlo y codificar), no en FAISS.
La calidad de la recuperación se medirá en DOC-16.

## Integración con la búsqueda (DOC-14)

`SearchEngine` crea el gestor de índices la primera vez que se pide
`method=semantic`, de modo que la API arranca sin cargar el modelo.

| Medición (`wikipedia_es`, índice ya construido, 32 consultas × 5, k=10) | p50 | p95 | Máximo |
| --- | --- | --- | --- |
| `semantic` (codificar la consulta + FAISS + armar resultados) | 37,1 ms | 44,4 ms | 49,7 ms |
| `bm25` (misma ejecución) | 13,5 ms | 16,7 ms | 20,2 ms |

La primera búsqueda semántica tardó 9,1 s: carga del modelo e índice desde
disco, sin codificar nada nuevo.
