# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

## [Sin publicar] — v1.1 (P1)

Ampliaciones opcionales DOC-36 a DOC-41 (#56–#61). La versión del paquete
sigue siendo 1.0.0 hasta que el propietario publique la siguiente.

### Añadido

- Panel de evaluación `#/evaluacion` con los resultados versionados de
  `evaluation/results/` (DOC-36).
- Preguntas con respuestas citadas mediante un modelo local opcional (Ollama
  en `127.0.0.1`), con citas validadas contra los fragmentos recuperados
  (DOC-38), e interfaz `#/preguntar` (DOC-39).
- Observabilidad (DOC-40):
  - registros JSON sin datos privados y `X-Request-ID`;
  - `GET /health/ready` y `GET /admin/metrics`;
  - `cli report`.
- Docker Compose local, solo en `127.0.0.1`, con datos en un volumen y check
  `docker-local` (DOC-41).

### Cambiado

- Los errores no controlados responden 500 con `request_id` en lugar de
  propagarse (DOC-40).
- `hash-password --env-file` escribe el hash entre comillas simples (DOC-41).

### Pendiente

- Google Docs privados mediante OAuth (DOC-37, #57): bloqueado hasta disponer
  de un proyecto OAuth del propietario.

## [1.0.0] — Entrega web

Primera versión utilizable desde el navegador. Issues DOC-24 a DOC-35
(#44–#55); el detalle de cada uno está en `docs/bitacora.md`.

### Añadido

- Autenticación local con roles Administrador y Usuario: contraseñas con
  scrypt, cookie `HttpOnly`, CSRF y límite de intentos (DOC-25).
- Interfaz web en `http://127.0.0.1:8000/`, accesible y sin dependencias
  externas (DOC-26):
  - carga, importación y listado con filtros (DOC-27);
  - visor con el fragmento resaltado y la página de origen (DOC-28);
  - buscador con BM25, TF-IDF, semántica e híbrida y comparación con BM25 (DOC-29).
- Edición y eliminación de documentos con purga de la caché léxica y del
  índice FAISS (DOC-30).
- Panel de índices y tareas de reindexación, sincronización semántica y OCR
  con estado real (DOC-31).
- Seguridad: CSP, cabeceras, rechazo de mutaciones sin sesión antes de leer
  el cuerpo y pruebas adversariales (DOC-32).
- Pruebas E2E en navegador real y check obligatorio `web-e2e` (DOC-33).
- Scripts de PowerShell, `.env` local, `cli doctor`, `cli demo` y check
  `windows-install` (DOC-34).
- Manual, informe técnico, guion de demostración, capturas reproducibles y
  `GET /version` (DOC-35).

### Cambiado

- Las rutas de documentos y la búsqueda en la colección `user` requieren
  sesión. Las mutaciones requieren el rol de Administrador y el token CSRF.

### Limitaciones conocidas

- Modo local monousuario. Sin HTTPS no debe exponerse a una red.
- Google Docs privados (OAuth) y RAG no están incluidos.
- No se verificó en un Windows de escritorio, sino en `windows-latest` de
  GitHub Actions.

## [0.2.0] y anteriores

Búsqueda semántica e híbrida, evaluación con MIRACL, OCR, Google Docs
públicos y licencia AGPL (DOC-12 a DOC-23). Ver `docs/bitacora.md`.
