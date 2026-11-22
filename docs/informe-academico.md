# DocuSearch AI — Informe técnico de la entrega v1.0

Proyecto académico, UAEM, periodo 2026-B. Este informe resume lo
implementado, cómo se evaluó y qué queda fuera, con enlaces a la evidencia
reproducible del repositorio. **Ninguna cifra de este documento es
estimada:** todas proceden de los archivos de `evaluation/results/`, de
`docs/pruebas.md` o de la integración continua.

> Nota sobre las fuentes: el documento de avance (`documentacion.pdf`) no
> estuvo disponible durante la entrega v1.0. La redacción de los requisitos
> RF/RNF en [`trazabilidad.md`](trazabilidad.md) se infirió del backlog y
> debe contrastarse con él.

## 1. Problema y objetivo

Buscar información dentro de una colección personal de documentos en español
(PDF, Word y texto) por palabras clave y por significado, y llegar al
fragmento y la página de origen, en una computadora sin GPU.

## 2. Arquitectura

```text
Navegador (HTML/CSS/JS, mismo origen)
   │  cookie de sesión HttpOnly + token CSRF
FastAPI ── SecurityMiddleware (CSP, cabeceras, filtros previos al cuerpo)
   ├── /auth        sesión local (scrypt, roles Administrador/Usuario)
   ├── /documents   carga → validación → extracción (PyMuPDF, python-docx, Tesseract)
   │                → fragmentación 200/30 con página → SQLite + originales
   ├── /search      BM25 · TF-IDF · semántica (MiniLM multilingüe + FAISS IP) · híbrida (RRF)
   └── /admin       estado de índices y tareas en segundo plano (un trabajador)
```

Decisiones y contratos: [`adr/0001-entrega-web-v1.md`](adr/0001-entrega-web-v1.md),
[`arquitectura.md`](arquitectura.md), [`api.md`](api.md).

## 3. Metodología de recuperación

- **Preprocesamiento** (`docs/preprocesamiento.md`): limpieza común; pipeline
  léxico con lematización spaCy `es_core_news_sm` y palabras vacías; pipeline
  semántico sin lematizar.
- **Fragmentación:** ventanas de 200 palabras con traslape de 30, conservando
  offsets y página.
- **Léxicos:** TF-IDF (coseno) y BM25 (`k1=1.5`, `b=0.75`) sobre los tokens.
- **Semántico:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
  (revisión fijada), **el mismo modelo para documentos y consulta**, vectores
  normalizados en `faiss.IndexFlatIP` (producto interno = coseno, búsqueda
  exacta) y ventanas de 128 tokens promediadas en los textos largos.
- **Híbrido:** Reciprocal Rank Fusion (k=60) de BM25 y semántica, con 100
  candidatos de cada uno.
- **Top-k por defecto:** 10.

## 4. Evaluación

### 4.1 Diseño

- **Conjunto principal:** MIRACL v1.0 español, split *dev* (Zhang et al.,
  2023): **648 consultas escritas por hablantes nativos** con juicios de
  relevancia humanos.
- **Corpus evaluado:** la unión de los **6410 pasajes juzgados** de esas
  consultas (6828 fragmentos). **No es el corpus MIRACL completo** (≈1,5 GB
  de Wikipedia), así que las cifras no son comparables con las tablas
  oficiales del benchmark. Los pasajes no relevantes juzgados son difíciles
  a propósito, porque otros sistemas los recuperaron.
- **Métricas:** Recall@1/5/10, MRR@10 y nDCG@10 (Järvelin y Kekäläinen,
  2002), por documento.
- **Significación:** prueba de aleatorización pareada con 10 000
  permutaciones frente a BM25.
- **Sin ajuste de parámetros** sobre este conjunto.
- **Reproducción:** `docs/evaluacion.md`; resultados versionados en
  `evaluation/results/miracl_es_dev.json`.

### 4.2 Resultados (648 consultas)

| Método | Recall@1 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 |
| --- | --- | --- | --- | --- | --- |
| TF-IDF | 0,138 | 0,521 | 0,811 | 0,683 | 0,660 |
| BM25 | 0,163 | 0,565 | 0,864 | 0,724 | 0,709 |
| Semántica | 0,167 | 0,564 | 0,827 | 0,733 | 0,695 |
| **Híbrida** | **0,167** | **0,602** | **0,913** | **0,761** | **0,752** |

| Frente a BM25 | Δ MRR@10 | p | Δ nDCG@10 | p |
| --- | --- | --- | --- | --- |
| TF-IDF | −0,041 | < 0,0001 | −0,049 | < 0,0001 |
| Semántica | +0,009 | 0,587 | −0,014 | 0,289 |
| Híbrida | +0,037 | 0,0018 | +0,044 | < 0,0001 |

**Lectura:**

- La **híbrida supera a BM25 de forma significativa** (nDCG@10 0,752 frente a
  0,709; Recall@10 0,913 frente a 0,864).
- La **semántica sola no es significativamente distinta** de BM25.
- TF-IDF queda por debajo de BM25.

BM25 sigue siendo el método por defecto porque no requiere componentes
opcionales; la híbrida es la recomendada cuando el extra semántico está
instalado. Las evaluaciones con consultas propias sobre `wikipedia_es` (v0.1
y v0.2) están en `docs/evaluacion.md` y se consideran secundarias, porque esas
consultas no tienen anotación humana independiente.

### 4.3 Rendimiento (RNF01: búsqueda < 2 s sobre índice caliente)

Motor sin HTTP, `wikipedia_es` (275 artículos, 1978 fragmentos), 48
consultas × 5 repeticiones, k=10, CPU (`docs/pruebas.md`):

| Método | p50 | p95 | Máximo |
| --- | --- | --- | --- |
| BM25 | 13,7 ms | 16,1 ms | 20,8 ms |
| TF-IDF | 15,0 ms | 17,0 ms | 18,5 ms |
| Semántica | 31,6 ms | 35,7 ms | 39,9 ms |
| Híbrida | 41,7 ms | 50,3 ms | 64,3 ms |

Costes que **no** forman parte de la búsqueda sobre índice caliente:

| Operación | Tiempo medido |
| --- | --- |
| Arrancar los índices léxicos (spaCy y caché de tokens) | 5,2 s |
| Cargar el modelo y el índice FAISS | 5,8 s |
| Construir FAISS desde cero | 113,6 s |

La suite repite en cada ejecución una prueba de latencia de menos de 2 s con
datos sintéticos.

### 4.4 Lo que no se evaluó

- No hay evaluación de RAG, porque RAG no forma parte de la entrega v1.0.
- No hay pruebas de usabilidad con personas ni con un lector de pantalla físico.
- No se midió la calidad del OCR con documentos escaneados reales.

## 5. Aplicación web y calidad

- **Funcionalidad:** inicio de sesión; carga de PDF, DOCX y TXT con OCR;
  importación de Google Docs públicos; listado con filtros; visor con el
  fragmento resaltado y la página; buscador con los 4 métodos y comparación;
  edición y eliminación coherentes con los índices; panel de reindexación.
  Ver el [manual](manual.md).
- **Seguridad:** ver [`seguridad.md`](seguridad.md), con el modelo de
  amenazas y la prueba que respalda cada control.
- **Pruebas** (detalle en [`pruebas.md`](pruebas.md)):
  - más de 500 pruebas de Python en 3.10, 3.11 y 3.12;
  - 39 pruebas en un navegador real (check `web-e2e`; la de paráfrasis con el
    modelo real corre en `semantic-model`), con un recorrido
    completo y uso solo con teclado;
  - pruebas con el modelo real (`semantic-model`), incluida la paráfrasis
    desde la web;
  - instalación limpia en Windows (`windows-install`).
- **Errores encontrados por las pruebas y corregidos durante la entrega:**
  - el enlace de salto se interpretaba como ruta;
  - la validación nativa ocultaba el mensaje de consulta vacía;
  - un "null" y un "undefined" aparecían en la interfaz;
  - los tokens y los vectores de documentos borrados se quedaban en disco;
  - FastAPI leía el cuerpo multipart antes de comprobar la sesión;
  - la contraseña de la prueba de Windows se serializaba mal en PowerShell 5.1.

  Detalle en [`bitacora.md`](bitacora.md).

## 6. Limitaciones

- Modo local monousuario, con sesiones en memoria. No es apto para exponerse
  a Internet sin HTTPS y los pasos de `seguridad.md`.
- Google Docs privados (OAuth) y RAG quedan fuera de la v1.0 (backlog P1:
  DOC-37 a DOC-39).
- En Windows se verificó en CI (`windows-latest`), no en un equipo de
  escritorio; el OCR y la búsqueda semántica no se verificaron en Windows.
- La evaluación usa el subconjunto de pasajes juzgados de MIRACL, no el
  corpus completo.

## 7. Referencias

- Cormack, G. V., Clarke, C. L. A. y Büttcher, S. (2009). Reciprocal rank
  fusion outperforms Condorcet and individual rank learning methods. *SIGIR*.
- Järvelin, K. y Kekäläinen, J. (2002). Cumulated gain-based evaluation of IR
  techniques. *ACM TOIS*, 20(4).
- Johnson, J., Douze, M. y Jégou, H. (2019). Billion-scale similarity search
  with GPUs. *IEEE Transactions on Big Data*.
- Reimers, N. y Gurevych, I. (2019). Sentence-BERT: Sentence embeddings using
  Siamese BERT-networks. *EMNLP-IJCNLP*.
- Reimers, N. y Gurevych, I. (2020). Making monolingual sentence embeddings
  multilingual using knowledge distillation. *EMNLP*.
- Robertson, S. y Zaragoza, H. (2009). The probabilistic relevance framework:
  BM25 and beyond. *Foundations and Trends in Information Retrieval*, 3(4).
- Zhang, X. et al. (2023). MIRACL: A multilingual retrieval dataset covering
  18 diverse languages. *TACL*, 11.
