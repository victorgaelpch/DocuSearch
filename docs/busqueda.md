# Búsqueda léxica (DOC-08, DOC-09)

Código: `backend/app/search/` — `lexical_corpus.py` (tokens con caché),
`ranking.py` (top-k), `tfidf.py`, `bm25.py`, `engine.py` (`SearchEngine`),
`evaluation.py`.

## Flujo

1. `SearchEngine` lee los fragmentos de una colección (`user` por defecto o
   `wikipedia_es`) en orden estable (`doc_id`, `ordinal`).
2. Tokeniza cada fragmento con el **pipeline léxico** de DOC-06. La consulta
   pasa por el mismo pipeline.
3. Los tokens se guardan en `data/indexes/lexical_tokens.json` (JSON, no
   `pickle`). La caché se invalida si cambia el texto del fragmento o la
   configuración del pipeline.
4. Los índices se construyen en memoria de forma perezosa. Se reconstruyen
   solos cuando cambia la firma de la colección en SQLite: número de
   documentos y de fragmentos, fecha de la última actualización y suma de
   offsets.
5. El resultado es una lista de `SearchHit` con `rank`, `score`, `method`,
   `doc_id`, `chunk_id`, `title`, `original_filename`, `snippet`, `page`,
   `page_start` y `page_end`.

## TF-IDF (DOC-08)

`sklearn.feature_extraction.text.TfidfVectorizer` sobre los tokens ya
normalizados (analizador identidad), con estos parámetros:

| Parámetro | Valor |
| --- | --- |
| `norm` | `l2` |
| `use_idf` / `smooth_idf` | `True` / `True` |
| `sublinear_tf` | `False` |
| `min_df` | 1 |

Con vectores L2, la puntuación es la **similitud coseno** entre consulta y
fragmento (entre 0 y 1). Los parámetros y la versión de scikit-learn se
exponen en `SearchEngine.describe()`.

## BM25 (DOC-09)

Implementación propia (`backend/app/search/bm25.py`) con índice invertido y
`numpy`. Es el **método por defecto** del motor.

| Parámetro | Valor |
| --- | --- |
| `k1` | 1.5 (saturación de la frecuencia del término) |
| `b` | 0.75 (normalización por longitud del fragmento) |
| idf | `ln(1 + (N − df + 0.5) / (df + 0.5))`, nunca negativo |
| Términos de la consulta | cada término único cuenta una vez |

TF-IDF y BM25 se construyen sobre **el mismo corpus léxico** (mismos tokens y
la misma `index_version`), por lo que se pueden comparar directamente. La
comparación está en `docs/evaluacion.md`.

## Ranking

- `k` por defecto **10**; se admiten enteros entre 1 y 100 (otro valor lanza
  `ValueError`).
- Solo se devuelven fragmentos con puntuación mayor que 0.
- **Orden determinista:** puntuación descendente y, en caso de empate,
  `chunk_id` ascendente. Para la misma versión del índice (`index_version`)
  el orden es siempre el mismo.
- Una consulta vacía, formada solo por stopwords o sin términos del
  vocabulario devuelve 0 resultados, sin error.

## Rendimiento medido (Windows, CPU, Python 3.12.10)

Sobre el corpus `wikipedia_es` (275 artículos, 1978 fragmentos, 24 384 términos):

| Operación | Tiempo |
| --- | --- |
| Primera construcción (lematiza todos los fragmentos) | 38,3 s |
| Consulta con la caché de tokens ya construida | ~17 ms |

Es una medición única en un equipo, no un banco de pruebas. La medición
sistemática del requisito de menos de 2 segundos queda para DOC-11.

## Limitaciones

- Los índices viven en memoria del proceso: se reconstruyen al reiniciar el
  servidor (rápido gracias a la caché de tokens).
- Un resultado es un fragmento, no un documento: un mismo documento puede
  aparecer varias veces en el top-k.
