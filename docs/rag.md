# Preguntas con respuestas citadas (RAG local opcional) — DOC-38/DOC-39

**Estado:** ampliación P1 de la v1.1. Está **desactivada por defecto**: sin
configurarla, DocuSearch funciona igual que en la v1.0 (búsqueda sin
generación) y `POST /ask` responde 503 `rag_unavailable`.

## Cómo funciona

1. **Recuperación:** se toman los `k` fragmentos (5 por defecto, máximo 10)
   más relevantes con la búsqueda híbrida, o con BM25 si no está el extra
   semántico. Es la misma búsqueda medida en la evaluación.
2. **Contexto:** cada fragmento se numera (`[S1]`, `[S2]`, …) y se envía
   entre delimitadores `<fuente>` como **datos no confiables**. Se neutralizan
   los delimitadores que el documento pudiera contener, para que un documento
   malicioso no pueda cerrar su fuente ni inventar otra.
3. **Generación:** un modelo local responde siguiendo estas reglas: usar solo
   las fuentes, citar cada afirmación con `[S#]`, responder `SIN_EVIDENCIA` si
   no basta, e ignorar las instrucciones que aparezcan dentro de las fuentes.
   El modelo no tiene herramientas ni acceso a la red desde DocuSearch.
4. **Verificación de citas:**
   - Solo cuentan las citas a fragmentos realmente recuperados; las demás se
     eliminan del texto y se informan (`invalid_citations`).
   - Una respuesta sin ninguna cita válida **no se muestra**
     (`status: "unsupported"`); en su lugar se ven los fragmentos recuperados.

| `status` | Significado |
| --- | --- |
| `answered` | Respuesta con al menos una cita válida |
| `insufficient_evidence` | El modelo indicó que las fuentes no bastan |
| `unsupported` | El modelo respondió sin citar fuentes válidas; la respuesta se descarta |
| `no_evidence` | No se recuperó ningún fragmento; no se llamó al modelo |

## Privacidad

Solo se admite un servidor **en esta misma computadora**: la URL debe ser
`127.0.0.1`, `localhost` o `::1`; cualquier otra se rechaza al arrancar. El
cliente no usa proxies del sistema. Así, los fragmentos de documentos
privados nunca salen del equipo.

## Configuración con Ollama

1. Instale Ollama desde https://ollama.com y descargue un modelo pequeño apto
   para CPU, por ejemplo `ollama pull llama3.2:3b` (≈2 GB) o `qwen2.5:3b`.
2. En `.env`:

   ```text
   DOCUSEARCH_RAG_PROVIDER=ollama
   DOCUSEARCH_RAG_MODEL=llama3.2:3b
   DOCUSEARCH_RAG_URL=http://127.0.0.1:11434
   DOCUSEARCH_RAG_TIMEOUT=120
   ```

3. Reinicie DocuSearch. `GET /ask/status` indica si Ollama responde y si el
   modelo está descargado.
4. Prueba manual con el modelo real:
   `$env:DOCUSEARCH_TEST_RAG = "1"; python -m pytest -q tests/test_rag.py -k real_local_ollama`.

## API

```http
POST /ask            (sesión + X-CSRF-Token)
{"question": "¿Qué abastece de agua potable a las ciudades?", "collection": "user", "method": "hybrid", "k": 5}
```

La respuesta incluye `answer`, `citations` (marcador, `doc_id`, `chunk_id`,
título, páginas y fragmento), `sources` (todo lo recuperado), `retrieval` (método
usado y tiempo), `generation` (proveedor, modelo y tiempo) y `disclaimer`.

| Código | Cuándo |
| --- | --- |
| 503 `rag_unavailable` | No hay proveedor configurado |
| 503 `rag_unreachable` | Ollama no responde o se agotó el tiempo |
| 502 `rag_provider_error` | Ollama devolvió un error (p. ej. modelo no descargado) |
| 429 `rag_busy` | Ya hay una respuesta generándose; se genera una a la vez para no saturar la CPU |

## Límites

- **No se ha evaluado la calidad de las respuestas**: no hay métricas de
  fidelidad ni de exactitud. Las citas garantizan trazabilidad, no que la
  respuesta sea correcta.
- La generación en CPU tarda segundos o minutos según el modelo. El
  requisito de menos de 2 s (RNF01) aplica a la recuperación, no a la
  generación.
- En esta entrega se probó con un proveedor simulado; la prueba con Ollama
  real (`test_real_local_ollama`) debe ejecutarse en un equipo que lo tenga
  instalado.
