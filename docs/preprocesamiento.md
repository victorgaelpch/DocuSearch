# Preprocesamiento de texto en español (DOC-06)

Código: `backend/app/nlp/normalization.py`, `lexical.py`, `semantic.py`.

Hay **dos pipelines separados** para no aplicar a los Transformers las reglas de
TF-IDF/BM25. Ambos parten de la misma limpieza (`clean_text`) y se aplican
igual a documentos y a consultas.

## 1. Limpieza común — `clean_text`

No elimina palabras; solo corrige artefactos:

| Paso | Ejemplo |
| --- | --- |
| Unicode NFC | `e` + tilde combinada → `é` |
| Ligaduras tipográficas | `ﬁnanzas` → `finanzas` |
| Guion suave, ancho cero, BOM, controles | `pala­bra` → `palabra` |
| Etiquetas HTML/XML y comentarios | `<b>texto</b>` → `texto` (no toca `a < b`) |
| Entidades HTML | `&amp;` → `&` |
| Palabras cortadas al final de línea | `recupe-\nración` → `recuperación` |
| Espacios repetidos y líneas en blanco | se colapsan; máximo un párrafo vacío |

Un texto que queda vacío tras la limpieza se trata como vacío (`is_blank`).

## 2. Pipeline léxico — `LexicalPipeline` (TF-IDF y BM25)

1. `clean_text`.
2. Tokenización con spaCy.
3. Se descartan puntuación, espacios, URLs, correos y tokens sin letras ni dígitos.
4. **Stopwords**: lista de spaCy para español (`spacy.lang.es.stop_words`)
   **menos** ~60 palabras con contenido útil en búsqueda que esa lista incluye
   (p. ej. `trabajo`, `estados`, `tiempo`, `nuevo`; ver `CONTENT_WORDS_KEPT`).
5. **Lematización** con `es_core_news_sm` (componentes `parser` y `ner`
   desactivados por velocidad).
6. Minúsculas.
7. **Plegado de tildes** (`búsqueda` → `busqueda`), conservando la `ñ`
   (`año` ≠ `ano`). *Decisión propia*: hace que las consultas escritas sin
   tildes coincidan; es configurable (`fold_accents=False`).

Los números se conservan (`1492`). La configuración exacta se expone en
`pipeline.config` y se guardará junto a los índices para reproducibilidad.

Si el modelo no está instalado, el pipeline funciona **sin lematizar** y lo
indica con `"lemmatizer": null` (o falla con `require_model=True`).

Rendimiento medido en local (Windows, CPU, Python 3.12): 100 textos de
200 palabras con `process_many` en ~2 s (~10 000 palabras/s).

## 3. Pipeline semántico — `prepare_semantic` (embeddings, v0.2)

`clean_text` + unión de líneas cortadas dentro de un párrafo. **No** quita
stopwords, no lematiza, no cambia mayúsculas, tildes ni puntuación: los modelos
de *sentence embeddings* usan las palabras funcionales y el contexto de la
oración.

## Instalación del modelo

```powershell
python -m pip install -e ".[dev,model]"
```

El extra `model` instala `es_core_news_sm` **3.8.0** desde la release oficial
de spaCy (versión fijada para reproducibilidad); el CI lo instala igual.

## Licencias

- spaCy: MIT.
- `es_core_news_sm`: **GNU GPL-3.0** (según los metadatos del modelo). Junto
  con PyMuPDF (AGPL-3.0), condiciona la licencia del proyecto; ver
  `docs/lectores.md`.

## Limitaciones

- El pipeline léxico no reconoce sinónimos ni paráfrasis (`coche` ≠
  `automóvil`); es la limitación que motiva la búsqueda semántica de v0.2 y
  queda cubierta por una prueba.
- La lematización de `es_core_news_sm` comete errores en nombres propios y
  términos técnicos; no se ha medido su precisión en el corpus.
- `documentacion.pdf` no estaba disponible: la configuración sigue el Issue
  #6 y el prompt del proyecto; revisar contra el documento académico.
