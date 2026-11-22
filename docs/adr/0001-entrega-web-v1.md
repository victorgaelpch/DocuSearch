# ADR 0001 — Contratos de la entrega web v1.0 (DOC-24)

- **Estado:** aceptado para la entrega v1.0.
- **Fecha:** 2026-11-22.
- **Commit de partida:** `840eaaa` (`main`, merge del PR #40, DOC-23). CI de
  `main` en verde (Python 3.10, 3.11, 3.12 y `semantic-model`).
- **Suite de partida:** `python -m pytest -q` → `379 passed, 7 skipped`
  (Linux, Python 3.13, sin extras `semantic`/`eval`).

## Contexto

DocuSearch ya resuelve el núcleo académico como **API**:

- ingesta de PDF, DOCX y TXT, con OCR en español para PDF escaneados;
- importación de Google Docs **públicos** por enlace;
- metadatos en SQLite, fragmentación 200/30 con página de origen;
- TF-IDF, BM25, búsqueda semántica (embeddings multilingües + FAISS
  `IndexFlatIP` sobre vectores normalizados) e híbrida (RRF);
- evaluación reproducible (corpus propio y MIRACL español).

Lo que **no existe** en `840eaaa` y bloquea una entrega web:

| Hueco | Consecuencia |
| --- | --- |
| Sin autenticación | Cualquiera con acceso al puerto lista, descarga y busca documentos privados y puede cargar archivos. |
| `frontend/` es un marcador | No hay interfaz; toda la demostración es por terminal o Swagger. |
| Sin edición ni borrado de documentos | Un documento cargado no se puede retirar del índice. |
| Reindexación solo por CLI | No hay estado de tareas ni panel de índices. |
| Google Docs privados | No hay OAuth; solo se importan documentos compartidos como "cualquier persona con el enlace". |
| RAG | No existe; no se declara como implementado. |

## Decisiones

### 1. Modo local monousuario

La entrega se ejecuta en `127.0.0.1` en una sola computadora. Hay **dos
roles** y como máximo **una cuenta por rol**, configuradas por entorno:

| Rol | Puede | Variable de contraseña (hash) |
| --- | --- | --- |
| `admin` (Administrador) | todo lo de `user` + cargar, importar, editar, eliminar, reindexar | `DOCUSEARCH_ADMIN_PASSWORD_HASH` |
| `user` (Usuario de consulta) | listar, ver, descargar y buscar documentos privados | `DOCUSEARCH_USER_PASSWORD_HASH` (opcional) |

- Sin variables configuradas **no hay cuenta**: no existe contraseña por
  defecto. Los endpoints privados responden 401.
- **No es multiusuario:** todos los documentos privados pertenecen a la
  instalación. No hay propietario por documento ni registro de cuentas.
- Las sesiones viven en memoria del proceso: reiniciar el servidor cierra
  todas las sesiones.

### 2. Datos públicos y privados

| Colección | Contenido | Acceso |
| --- | --- | --- |
| `user` | Documentos cargados o importados | Privado: requiere sesión |
| `wikipedia_es`, `miracl_es` | Corpus experimentales públicos | Búsqueda anónima permitida |

### 3. Sesión y CSRF

- Cookie `docusearch_session`: `HttpOnly`, `SameSite=Strict`, `Path=/`;
  `Secure` configurable (desactivada por defecto porque la demo usa HTTP en
  `127.0.0.1`).
- Nunca se envían credenciales por query string ni se guardan tokens en
  `localStorage`.
- Toda mutación (`POST`, `PATCH`, `PUT`, `DELETE`) autenticada exige la
  cabecera `X-CSRF-Token` con el token de la sesión y, si el navegador envía
  `Origin`, que coincida con el del servidor.
- Expiración por inactividad y absoluta; `logout` invalida la sesión en el
  servidor.

### 4. Frontend en el mismo origen

HTML/CSS/JS modular servido por FastAPI desde `frontend/` (sin Node en
ejecución, sin CDN). Swagger (`/docs`) y `/openapi.json` se conservan. Node y
Playwright solo como herramientas de desarrollo y CI para las pruebas E2E.

### 5. Compatibilidad de rutas

Las rutas existentes no cambian de forma ni de respuesta exitosa. El único
cambio de comportamiento es que ahora exigen sesión (401) o rol de
administrador (403). Las rutas nuevas se añaden sin prefijo de versión,
como las actuales.

## Contrato HTTP v1.0

Formato de error único (ya usado por la API):

```json
{"error": {"code": "not_found", "message": "documento no encontrado", "doc_id": "…"}}
```

| Método | Ruta | Acceso | Estado | Issue |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | público | existe | DOC-01 |
| `POST` | `/auth/login` | público (limitado por intentos) | nuevo | DOC-25 |
| `POST` | `/auth/logout` | sesión + CSRF | nuevo | DOC-25 |
| `GET` | `/auth/me` | público (indica si hay sesión) | nuevo | DOC-25 |
| `POST` | `/documents` | admin + CSRF | existe → protegido | DOC-04/25 |
| `POST` | `/documents/import` | admin + CSRF | existe → protegido | DOC-22/25 |
| `GET` | `/documents` | user | existe → protegido; filtros nuevos | DOC-04/25/27 |
| `GET` | `/documents/{id}` | user | existe → protegido | DOC-04/25 |
| `GET` | `/documents/{id}/download` | user | existe → protegido | DOC-04/25 |
| `GET` | `/documents/{id}/chunks` | user | existe → protegido | DOC-07/25 |
| `GET` | `/documents/{id}/content` | user | nuevo (visor PDF en línea) | DOC-28 |
| `PATCH` | `/documents/{id}` | admin + CSRF | nuevo (título y metadatos) | DOC-30 |
| `DELETE` | `/documents/{id}` | admin + CSRF | nuevo | DOC-30 |
| `GET` | `/search` | público para corpus; user para `collection=user` | existe → protegido para `user` | DOC-10/25 |
| `GET` | `/search/index` | ídem | existe → protegido para `user` | DOC-10/25 |
| `GET` | `/admin/indexes` | admin | nuevo | DOC-31 |
| `POST` | `/admin/indexes/{colección}/jobs` | admin + CSRF | nuevo | DOC-31 |
| `GET` | `/admin/jobs/{job_id}` | admin | nuevo | DOC-31 |

Códigos HTTP: 401 `not_authenticated` (sin sesión o expirada), 403
`forbidden` (rol insuficiente) o `csrf_failed`, 429 `too_many_attempts`
(login), 409 `job_running` (ya hay una reindexación en la colección).

### Tareas de reindexación

Estados: `pending` → `running` → `succeeded` | `failed`. El progreso solo se
publica cuando existe una cifra real (documentos procesados / total); en
otro caso el estado es indeterminado. Una tarea por colección a la vez. Las
búsquedas siguen sirviendo el índice anterior hasta que el nuevo está
completo (los índices léxicos se reemplazan atómicamente bajo un cerrojo; el
FAISS se escribe a un temporal y se renombra).

## Trazabilidad

La matriz RF01–RF08 / RNF01–RNF07, con evidencia y pendientes, está en
[`docs/trazabilidad.md`](../trazabilidad.md).

## Consecuencias

- Las pruebas existentes que llaman a endpoints privados deben iniciar
  sesión con una cuenta de prueba creada en el propio test (hash generado en
  la prueba, nunca versionado). La protección no se desactiva para tests.
- El modo local no es apto para exponerse a Internet: hace falta TLS, proxy
  inverso y gestión de cuentas real (ver DOC-32).
- Google Docs privados (DOC-37) dependen de un proyecto OAuth del
  propietario; sin él queda bloqueado externamente.
