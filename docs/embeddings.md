# Servicio de embeddings multilingüe (DOC-12)

Código: `backend/app/nlp/embeddings.py`. Pruebas: `tests/test_embeddings.py`.

Convierte fragmentos y consultas en vectores densos para la búsqueda
semántica de v0.2. Por ahora solo produce vectores; el índice FAISS es DOC-13
y la búsqueda, DOC-14.

## Modelo

| Campo | Valor |
| --- | --- |
| Modelo | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| Revisión fijada | `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` |
| Licencia | Apache-2.0 (según la ficha del modelo en Hugging Face) |
| Dimensión | 384 |
| Longitud máxima | 128 tokens (126 de contenido) |
| Descarga | ~458 MB en la caché local, solo la primera vez |
| Dispositivo | CPU (no requiere GPU) |

## Instalación

```powershell
python -m pip install -e ".[dev,model,semantic]"
python -m backend.app.cli embeddings           # descarga el modelo y muestra la configuración
```

El extra `semantic` instala `sentence-transformers` 6.x, que trae PyTorch
(licencias Apache-2.0/BSD). En Windows y macOS el PyTorch de PyPI ya es de
CPU. En Linux, para no descargar la variante CUDA (varios GB), instala antes
la de CPU:

```bash
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Sin el extra, la aplicación y la búsqueda léxica funcionan igual. El
servicio solo falla al usarlo, con `EmbeddingUnavailableError` y un mensaje
que indica cómo instalarlo.

## Configuración

| Variable | Por defecto | Uso |
| --- | --- | --- |
| `DOCUSEARCH_MODEL_CACHE` | caché de Hugging Face (`~/.cache/huggingface`) | Carpeta del modelo; nunca dentro del repositorio |
| `DOCUSEARCH_EMBEDDING_BATCH_SIZE` | 32 | Segmentos por lote |
| `HF_HUB_OFFLINE=1` | — | Variable de Hugging Face: usa solo la caché, sin red |

`encoder.config` expone modelo, revisión, dimensión, estrategia de textos
largos, normalización y la configuración del pipeline semántico. DOC-13 la
guardará junto al índice para detectar cuándo hay que reconstruirlo.

## Cómo se codifica un texto

1. `prepare_semantic` (DOC-06): limpia artefactos, pero conserva stopwords,
   mayúsculas, tildes y puntuación.
2. **Ventanas.** El modelo solo lee 128 tokens, y los fragmentos de 200
   palabras son más largos. Medido sobre los 1978 fragmentos de
   `wikipedia_es`:
   - mediana de 304 tokens, percentil 90 de 345 y máximo de 497 (1,56 tokens
     por palabra);
   - el **96 %** supera el límite;
   - si se truncaran, el modelo vería solo el **43 %** de los tokens del corpus.

   Por eso el texto se divide en ventanas de ≤126 tokens, cortando al inicio
   de una palabra (`split_windows`).
3. Se codifica cada ventana (normalizada), se promedian ponderando por su
   número de tokens y se vuelve a normalizar (L2, `float32`). El producto
   interno es, por tanto, el coseno.
4. Un texto vacío produce el vector cero: no se parece a nada.

`long_text="truncate"` reproduce el comportamiento por defecto de la
biblioteca (solo los primeros 128 tokens). La estrategia por ventanas se
eligió por cobertura del texto, **no** midiendo la calidad de recuperación con
las consultas de evaluación. Comparar ambas estrategias corresponde a DOC-16,
con un conjunto de desarrollo separado.

Las consultas pasan por la misma función. Casi siempre caben en una sola
ventana.

## Resultados medidos (Windows, CPU de 16 hilos, PyTorch 2.15 con 8 hilos)

- Carga del modelo desde la caché: 1,3–8,9 s según el estado de la caché de
  disco. La primera ejecución con descarga tardó 55 s.
- Codificar los 1978 fragmentos de `wikipedia_es` con ventanas: **105 s**
  (18,8 fragmentos/s). Con truncado, una muestra de 200 fragmentos tardó 4,1 s.
- Codificar una consulta (32 consultas × 5): p50 de 14,3 ms, p95 de 18,4 ms y
  máximo de 54,5 ms.
- Codificar el mismo texto con otro tamaño de lote varía como mucho 7,5·10⁻⁸;
  repetir con el mismo lote da el mismo resultado (tolerancia 10⁻⁶ en las
  pruebas).
- Ejemplos (coseno con ventanas):
  - *"infección que contagian los zancudos"* frente a una definición de dengue:
    0,44; frente a un texto de fotosíntesis: −0,06.
  - En un fragmento cuya segunda mitad trata del café, la consulta *"cultivo
    de café"* obtiene 0,50 con ventanas y 0,07 truncando.

```powershell
python -m backend.app.cli embeddings --collection wikipedia_es [--limit 200]
```

## Pruebas

- Por defecto no se descarga nada. `HashingEncoder` (determinista, solo para
  pruebas) y un modelo simulado con la interfaz de `SentenceTransformer`
  cubren las ventanas, la ponderación, la normalización, los textos vacíos,
  la configuración y los errores (extra ausente, fallo de carga).
- Las pruebas con el modelo real tienen la marca `semantic_model` y se omiten
  salvo que se pidan explícitamente:

```powershell
$env:DOCUSEARCH_TEST_SEMANTIC_MODEL = "1"
python -m pytest -q tests/test_embeddings.py
```

El CI no las ejecuta todavía; un job opcional con caché del modelo queda para
DOC-17.

## Limitaciones

- Promediar ventanas diluye un fragmento que mezcla temas. Con 200 palabras
  suele haber como mucho 3 ventanas.
- El modelo se entrenó con paráfrasis generales; no se ha medido en textos
  técnicos del usuario.
- `documentacion.pdf` no estaba disponible para contrastar la elección del
  modelo y la estrategia de textos largos.
