# Observabilidad y medición de rendimiento (DOC-40)

Herramientas ligeras para diagnosticar fallos durante una demostración local
y medir el rendimiento sin exponer datos privados. **No es monitoreo de
producción**: no hay Prometheus, alertas externas ni retención de métricas.

## Registros

Cada petición produce una línea JSON en la salida de error del servidor,
registro `docusearch`; el nivel se ajusta con `DOCUSEARCH_LOG_LEVEL`, que por
defecto es `INFO`:

```json
{"ts": "2026-11-22T09:41:02.118Z", "level": "info", "event": "request", "request_id": "3f9c0a1b2d4e5f60", "method": "GET", "path": "/documents/{doc_id}", "status": 200, "duration_ms": 4.21}
{"ts": "2026-11-22T09:41:03.502Z", "level": "info", "event": "search", "method": "bm25", "collection": "user", "k": 10, "results": 3, "took_ms": 2.6, "cold": false}
```

- **Nunca se registran:** cadenas de consulta, texto buscado, cuerpos de
  petición, contenido de documentos, títulos, cookies ni contraseñas. Las rutas
  se registran como plantilla (`/documents/{doc_id}`), sin el identificador.
- **`X-Request-ID`:** va en todas las respuestas, también en los rechazos de
  seguridad. Si el cliente envía uno válido (8–64 caracteres `A-Za-z0-9_-`),
  se conserva.
- **Errores no controlados:** responden 500 con
  `{"error": {"code": "internal_error", "request_id": "…"}}`, sin detalles
  internos, y se registran como `unhandled_error` con el tipo de excepción y
  las últimas líneas de la traza. Para diagnosticar, busque el `request_id` en
  el registro.

## Salud y preparación

| Ruta | Uso |
| --- | --- |
| `GET /health` | Vida: el proceso responde (siempre 200) |
| `GET /health/ready` | Preparación: 200 `ready` si base de datos, carpeta de datos, modelo de spaCy y cuenta de Administrador están bien; si no, 503 `not_ready`. Informa además los componentes opcionales `semantic`, `ocr` y `rag_configured`. Solo valores verdadero/falso |
| `GET /admin/metrics` | Administrador. Latencias por método desde el arranque, separando la primera consulta tras construir un índice (en frío) de las siguientes (en caliente; p50, p95, máximo); memoria residente; duración de las últimas tareas por tipo |

El panel **Índices** muestra la tabla de rendimiento y avisa si el p95 en
caliente de algún método supera 2 s (RNF01).

## Informe reproducible

```powershell
python -m backend.app.cli report --repeats 5 --output informe.json
```

1. Crea una copia temporal de la demostración sintética.
2. Mide la ingesta por documento (incluido el OCR del PDF escaneado), la
   primera consulta por método (en frío: carga de spaCy o del modelo y
   construcción del índice) y las consultas en caliente.
3. Pasa por la **pila HTTP completa** (middleware de seguridad y de registro
   incluidos) y también registra el tiempo del motor.
4. Anota la máquina (sistema, Python, CPU, RAM) para poder comparar.
5. Devuelve código 1 si el p95 en caliente supera 2 s.

### Resultados medidos

**Entorno de desarrollo de la entrega** (contenedor Linux, Python 3.13, 2
CPU, 7,8 GB de RAM, sin GPU; demostración: 4 documentos, 4 fragmentos; 6
consultas × 5 repeticiones; `k=10`):

| Método | 1.ª consulta (frío) | p50 HTTP | p95 HTTP | máx. HTTP | p50 motor |
| --- | --- | --- | --- | --- | --- |
| BM25 | 628 ms | 7,6 ms | 10,4 ms | 11,3 ms | 2,5 ms |
| TF-IDF | 753 ms | 6,1 ms | 9,5 ms | 9,9 ms | 2,4 ms |

| Ingesta | Tiempo |
| --- | --- |
| PDF escaneado de 1 página (OCR Tesseract, español) | 734 ms |
| PDF de 2 páginas con texto | 18 ms |
| DOCX con tabla | 61 ms |
| TXT | 10 ms |

Memoria residente al final: 304 MB (solo métodos léxicos).

**Windows** (`windows-latest` de GitHub Actions, check `windows-install`):
la primera búsqueda BM25 por HTTP sobre la demostración, en frío y con carga
de spaCy incluida, tardó **799 ms**.

**Corpus mayor y métodos semánticos** (`wikipedia_es`: 275 artículos, 1978
fragmentos; ver `docs/pruebas.md`): p95 en caliente de 16 ms (BM25) a 50 ms
(híbrida); cargar el modelo y el índice FAISS tarda 5,8 s. La semántica y la
híbrida no se midieron en este entorno porque no tiene el extra `semantic`.

Todas las búsquedas en caliente quedan **muy por debajo de 2 s**. Los costes
en frío (cargar modelos, construir índices, OCR) se separan porque RNF01 se
refiere al índice caliente.

## Límites

- Las métricas viven en memoria y se pierden al reiniciar.
- Cifras de un corpus pequeño: con miles de documentos la latencia crece.
  Repita `report` con sus datos (`docs/pruebas.md` tiene la medición con
  `wikipedia_es`).
- No hay alertas activas: el aviso aparece en el panel y en el código de
  salida de `report`.
