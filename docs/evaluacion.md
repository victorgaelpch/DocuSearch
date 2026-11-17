# Evaluación de la línea base léxica: TF-IDF vs BM25 (DOC-09)

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
