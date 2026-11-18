# Evaluación de la recuperación (DOC-09, DOC-16)

## Evaluación v0.2: léxica vs semántica vs híbrida (DOC-16)

Consultas: `evaluation/queries_wikipedia_es_v2.json`. Resultados por
consulta: `evaluation/results/wikipedia_es_v2_test.json` (prueba) y
`evaluation/results/v2_dev_semantic_{mean,truncate}.json` (desarrollo).

```powershell
python -m backend.app.cli semantic-index --collection wikipedia_es
python -m backend.app.cli evaluate --queries evaluation/queries_wikipedia_es_v2.json --split test --methods tfidf bm25 semantic hybrid --output evaluation/results/wikipedia_es_v2_test.json
```

### Metodología

- **Corpus:** el mismo `wikipedia_es` v1 (275 artículos, 1978 fragmentos).
- **Consultas nuevas:** 48 en español.
  - **Desarrollo (16):** 8 léxicas y 8 paráfrasis. Solo para decisiones de
    diseño.
  - **Prueba (32):** 12 léxicas y 20 paráfrasis. Solo para este informe.
  - Ningún artículo relevante coincide con los del conjunto v1 (lo comprueba
    una prueba automática).
- **Anotación:** se redactaron y anotaron por título **antes** de ejecutar
  ningún método; el archivo se confirmó en un commit propio antes de evaluar.
  Las redactó el asistente de desarrollo: **siguen pendientes de revisión
  humana** y, hasta entonces, el Issue #27 no se da por cerrado.
- **Sin ajuste con el conjunto de prueba:**
  - BM25 usa `k1=1.5` y `b=0.75`.
  - RRF usa `k=60` (valor del artículo original).
  - La semántica no tiene umbral más allá de coseno > 0.
  - La única decisión que se contrastó con datos (la estrategia de textos
    largos) se tomó con el conjunto de desarrollo.
- **Significación:** prueba de aleatorización pareada (*sign-flip*) sobre
  MRR@10 y nDCG@10 por consulta, de cada método frente a BM25.
  - 10 000 permutaciones con semilla fija; es exacta con 16 consultas o
    menos.
  - p < 0,05 se considera significativo; no se corrige por comparaciones
    múltiples.
- **Entorno:** Windows, CPU, Python 3.12.10.
  - spaCy 3.8 con `es_core_news_sm` 3.8.0;
  - `sentence-transformers` 6.3.0, PyTorch 2.15.0 y `faiss-cpu` 1.16.0;
  - modelo `paraphrase-multilingual-MiniLM-L12-v2`, revisión `e8f8c211…`.

### Decisión con el conjunto de desarrollo: ventanas frente a truncado

| Estrategia (semantic, 16 consultas dev) | Recall@1 | Recall@10 | MRR@10 | nDCG@10 |
| --- | --- | --- | --- | --- |
| Ventanas promediadas (`mean`, por defecto) | 0.500 | 0.875 | 0.617 | 0.679 |
| Truncado a 128 tokens (`truncate`) | 0.438 | 0.938 | 0.565 | 0.652 |

Las ventanas ganan en 6 consultas y pierden en 3 (MRR@10 +0,053, p=0,50).
No hay evidencia para cambiar la estrategia elegida en DOC-12 por cobertura,
así que se mantiene `mean`. Por tipo de consulta el resultado es mixto: en
las paráfrasis de desarrollo el truncado fue algo mejor.

### Resultados en el conjunto de prueba (32 consultas)

| Método | Consultas | Tipo | Recall@1 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tfidf | 32 | todas | 0.641 | 0.875 | 0.922 | 0.754 | 0.788 |
| tfidf | 12 | léxicas | 0.875 | 0.958 | 0.958 | 0.944 | 0.926 |
| tfidf | 20 | paráfrasis | 0.500 | 0.825 | 0.900 | 0.639 | 0.706 |
| bm25 | 32 | todas | 0.766 | 0.875 | 0.953 | 0.840 | 0.861 |
| bm25 | 12 | léxicas | 0.958 | 0.958 | 0.958 | 1.000 | 0.968 |
| bm25 | 20 | paráfrasis | 0.650 | 0.825 | 0.950 | 0.745 | 0.797 |
| semantic | 32 | todas | 0.688 | 0.812 | 0.922 | 0.777 | 0.797 |
| semantic | 12 | léxicas | 0.875 | 0.958 | 0.958 | 0.944 | 0.926 |
| semantic | 20 | paráfrasis | 0.575 | 0.725 | 0.900 | 0.677 | 0.720 |
| hybrid | 32 | todas | 0.781 | 0.891 | 0.922 | 0.852 | 0.861 |
| hybrid | 12 | léxicas | 0.958 | 0.958 | 0.958 | 1.000 | 0.968 |
| hybrid | 20 | paráfrasis | 0.675 | 0.850 | 0.900 | 0.764 | 0.797 |

Frente a BM25, sobre todas las consultas de prueba:

| Método | Δ MRR@10 | Gana / pierde | p | Δ nDCG@10 | p |
| --- | --- | --- | --- | --- | --- |
| tfidf | −0,087 | 0 / 7 | **0,014** | −0,072 | **0,014** |
| semantic | −0,063 | 4 / 8 | 0,305 | −0,064 | 0,169 |
| hybrid | +0,012 | 3 / 4 | 0,847 | −0,000 | 1,000 |

### Lectura

- **La búsqueda semántica no supera a BM25 en este corpus**, ni siquiera en
  las paráfrasis (MRR@10 de 0,677 frente a 0,745). La diferencia no es
  significativa (p=0,31), pero tampoco hay ventaja.
- **La híbrida empata con BM25** (MRR@10 de 0,852 frente a 0,840; p=0,85). Es
  el mejor método en Recall@1 (0,781) y Recall@5 (0,891), y en las paráfrasis
  (MRR@10 de 0,764), pero con diferencias pequeñas y no significativas.
- **La única diferencia significativa** es que BM25 supera a TF-IDF (p=0,014),
  lo que confirma el resultado de DOC-09 con consultas nuevas.
- **La mejora de v1 a v2 del pipeline léxico** (DOC-11) se midió con el mismo
  conjunto con que se encontró. Con consultas nuevas, BM25 v2 obtiene MRR@10
  de 0,840. No hay medición de v1 sobre estas consultas, así que no se puede
  afirmar cuánto aportó.

**Análisis de errores (MRR@10 por consulta, prueba):**

- **La semántica acierta donde BM25 falla.** Son consultas sin las palabras
  del artículo:
  - T18, *"mapa de las estrellas del cielo"* → Carta estelar: BM25 0,25,
    semántica 1,0.
  - T25, *"prueba de laboratorio que mide la sensibilidad de una bacteria…"* →
    Antibiograma: BM25 0,5, semántica 1,0.
  - T16, *"veneno clásico…"* → Arsénico: BM25 0,5, semántica 1,0.
- **La semántica falla donde BM25 acierta.** El artículo contiene literalmente
  una palabra rara de la consulta:
  - T14 *"…pilas recargables de níquel"* → Cadmio: semántica 0,14.
  - T31 *"…países emergentes por endeudarse…"* → EMBI: semántica 0,10.
  - T02 → Elemento sintético: semántica 0,33.
- **La híbrida conserva las ganancias de ambos:** 1,0 en T16, T18 y T25, y en
  T02, T13 y T24. Pierde parte en T14 (0,33) y T31 (0,5).
- **Ningún método resuelve** T22 (Código inflado), T26 (Coproparasitología)
  ni T27 (Scordatura): son conceptos que la consulta describe con palabras
  que no aparecen en el texto.

**Por qué la semántica rinde menos de lo esperado (hipótesis, no medidas):**

1. Muchas "paráfrasis" comparten palabras poco frecuentes con el cuerpo del
   artículo, aunque no con su título. Eso favorece a BM25: Wikipedia define
   los conceptos con esas mismas palabras.
2. `MiniLM-L12` multilingüe es un modelo pequeño y general.
3. Promediar las ventanas de un fragmento diluye la señal de un término
   concreto.

Modelos mayores (p. ej. `multilingual-e5`) o reordenar con un *cross-encoder*
son líneas para una fase posterior. Habría que probarlas con el conjunto de
desarrollo, no con el de prueba.

### Conjunto v1 con los cuatro métodos (no independiente)

`evaluation/results/wikipedia_es_v1_queries_v02_methods.json`. Estas 32
consultas ya se habían usado en DOC-09 y DOC-11, así que solo sirven de
referencia:

| Método | MRR@10 | nDCG@10 | Δ MRR@10 vs BM25 (p) |
| --- | --- | --- | --- |
| tfidf | 0.845 | 0.878 | −0,061 (0,132) |
| bm25 | 0.905 | 0.921 | — |
| semantic | 0.785 | 0.814 | −0,121 (0,092) |
| hybrid | 0.861 | 0.893 | −0,045 (0,325) |

### Recomendación

Mantener **BM25 como método por defecto**. Ofrecer `hybrid` como alternativa
para consultas descriptivas. La búsqueda semántica sola no se recomienda
como método principal con este modelo.

### Limitaciones

- 32 consultas de prueba y un corpus pequeño, con temas muy separados. Las
  diferencias de unas pocas consultas cambian las medias, y solo la
  comparación con TF-IDF es significativa.
- Consultas redactadas por el asistente, no por usuarios reales ni por un
  anotador independiente. Necesitan revisión humana.
- La relevancia es binaria y por título, así que un artículo relacionado
  (p. ej. Elemento químico para T02) cuenta como no relevante.
- `documentacion.pdf` no estaba disponible para contrastar la metodología.

---

## Evaluación v0.1: TF-IDF vs BM25 (DOC-09)

Código: `backend/app/search/evaluation.py`. Consultas:
`evaluation/queries_wikipedia_es.json`. Resultados completos, por consulta:
`evaluation/results/wikipedia_es_tfidf_bm25.json`.

```powershell
python -m backend.app.cli evaluate --output evaluation/results/wikipedia_es_tfidf_bm25.json
```

## Metodología

- **Corpus:** `wikipedia_es` v1, con 275 artículos y 1978 fragmentos de 200/30
  (ver `docs/corpus.md`). Versión del índice: `b114c3e4d67f8897`.
- **Consultas:** 32 en español. 15 son **léxicas** (comparten términos con el
  artículo) y 17 son **paráfrasis o sinónimos** (describen el concepto sin usar
  las palabras del título).
- **Anotación:** se redactaron a partir de conocimiento general y se anotaron
  por título **antes** de ejecutar cualquier método. Relevancia binaria; 3
  consultas tienen más de un documento relevante. Las redactó el asistente de
  desarrollo, no un anotador humano independiente: **deben revisarse** antes
  de usarlas en el informe académico.
- **Sin ajuste de parámetros:** BM25 usa `k1=1.5` y `b=0.75`, y TF-IDF los
  valores por defecto de scikit-learn. Al no ajustar nada, no hay fuga entre
  ajuste y evaluación. Si en el futuro se ajustan parámetros, habrá que
  separar un conjunto de desarrollo.
- **Nivel de documento:** se recuperan los 100 mejores fragmentos, se agrupan
  por documento conservando su mejor posición y se calculan Recall@1/5/10,
  MRR@10 y nDCG@10.
- **Entorno:** Windows, CPU, Python 3.12.10, spaCy 3.8.18 con
  `es_core_news_sm` 3.8.0 y scikit-learn 1.9.1.

## Resultados con el pipeline léxico v2 (vigente)

Mismas consultas y corpus. El pipeline indexa el lema y la forma superficial
(ver `docs/preprocesamiento.md`). Versión del índice: `8bb022c3ffe1f1d6`.
Archivo: `evaluation/results/wikipedia_es_tfidf_bm25_v2.json`.

| Método | Consultas | Tipo | Recall@1 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tfidf | 32 | todas | 0.750 | 0.958 | 1.000 | 0.845 | 0.878 |
| tfidf | 15 | léxicas | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| tfidf | 17 | paráfrasis | 0.529 | 0.922 | 1.000 | 0.708 | 0.770 |
| bm25 | 32 | todas | 0.792 | 0.958 | 1.000 | 0.905 | 0.921 |
| bm25 | 15 | léxicas | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| bm25 | 17 | paráfrasis | 0.608 | 0.922 | 1.000 | 0.822 | 0.851 |

**Sobre el cambio:** la corrección no se eligió mirando estas métricas. Surgió
de un defecto funcional detectado por las pruebas de extremo a extremo
(DOC-11): la consulta `dengue` no encontraba el artículo Dengue. Aun así, se
midió sobre el mismo conjunto de consultas, así que la mejora de v1 a v2
(BM25: MRR@10 de 0.880 a 0.905) debe confirmarse con consultas nuevas. Con v2,
BM25 ya recupera P12 (Desinflación), aunque en la posición 7.

## Resultados con el pipeline léxico v1 (histórico, ejecución del 2026-11-17)

| Método | Consultas | Tipo | Recall@1 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tfidf | 32 | todas | 0.698 | 0.880 | 1.000 | 0.828 | 0.856 |
| tfidf | 15 | léxicas | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| tfidf | 17 | paráfrasis | 0.431 | 0.774 | 1.000 | 0.677 | 0.729 |
| bm25 | 32 | todas | 0.760 | 0.948 | 0.969 | 0.880 | 0.890 |
| bm25 | 15 | léxicas | 0.933 | 1.000 | 1.000 | 0.967 | 0.975 |
| bm25 | 17 | paráfrasis | 0.608 | 0.902 | 0.941 | 0.804 | 0.815 |

**Latencia por consulta** con profundidad 100, ya con los índices construidos
y en una sola ejecución: TF-IDF tuvo una media de 71,0 ms (máximo 141,2 ms) y
BM25 una media de 73,6 ms (máximo 103,0 ms).

### Lectura

- BM25 supera a TF-IDF en MRR@10 (0.880 frente a 0.828) y en nDCG@10 (0.890
  frente a 0.856) sobre el total, sobre todo en las paráfrasis.
- TF-IDF recupera todos los relevantes en el top-10, pero los coloca más
  abajo. BM25 falla una paráfrasis por completo: P12, *"reducción del ritmo al
  que suben los precios"* → Desinflación, no aparece en su top-10. En una
  consulta léxica (L07, aluminio) BM25 pone el relevante en la posición 2.
- Ambos métodos bajan claramente en las paráfrasis. Esta es la brecha que la
  búsqueda semántica de v0.2 debe reducir, y BM25 es la línea base contra la
  que se comparará.

## Advertencias

- El corpus es **pequeño** y sus temas están muy separados (constelaciones,
  elementos, lenguajes…). Eso facilita la recuperación; las cifras no se
  pueden extrapolar a un corpus general.
- 32 consultas son pocas para afirmar diferencias significativas; no se
  calcularon pruebas estadísticas.
- Algunas paráfrasis comparten palabras con el texto del artículo, aunque no
  con su título. Por ejemplo, P04, *"infección de la vejiga urinaria"*, coincide
  con palabras de la definición de cistitis.
- `documentacion.pdf` no estaba disponible para comparar esta metodología con
  la del documento académico.
