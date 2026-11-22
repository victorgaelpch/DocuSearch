# Docker Compose (opcional) — DOC-41

Segunda forma de arrancar DocuSearch en un entorno reproducible. **La
instalación nativa en Windows ([`instalacion-windows.md`](instalacion-windows.md))
sigue siendo la principal** y no depende de Docker.

## Arranque

```bash
# 1. Cuenta de Administrador (el hash se guarda entre comillas simples en .env, que no se versiona)
python -m backend.app.cli hash-password --env-file .env
#    sin Python en el anfitrión: docker compose run --rm --no-deps docusearch python -m backend.app.cli hash-password
#    y pegue el resultado en .env como  DOCUSEARCH_ADMIN_PASSWORD_HASH='scrypt$…'

# 2. Construir y arrancar (la primera vez tarda varios minutos)
docker compose up -d --build

# 3. Abrir http://127.0.0.1:8000/  ·  estado: docker compose ps (healthy)
# 4. Demostración (opcional)
docker compose exec docusearch python -m backend.app.cli demo
```

## Qué hace `compose.yaml`

| Aspecto | Configuración |
| --- | --- |
| Red | Puerto publicado **solo en `127.0.0.1:8000`**: no es accesible desde otras máquinas |
| Datos | Volumen con nombre `docusearch-data` en `/data`: originales, SQLite, índices, caché de modelos. **Nunca dentro de la imagen**; persisten al reiniciar y al recrear el contenedor |
| Secretos | Ninguno en la imagen ni en `compose.yaml`; se leen de `.env` |
| Endurecimiento | Usuario sin privilegios (uid 10001), sistema de archivos de solo lectura (salvo `/data` y `/tmp`), `cap_drop: ALL`, `no-new-privileges` |
| Salud | `HEALTHCHECK` sobre `GET /health/ready`: queda `unhealthy` si falta la cuenta de Administrador |
| Reinicio | `restart: unless-stopped` |
| Procesos | Un solo worker: las sesiones y las tareas viven en memoria |

Argumentos de construcción (en `compose.yaml`):

| Argumento | Por defecto | Efecto |
| --- | --- | --- |
| `WITH_OCR` | `1` | Instala Tesseract con español (~40 MB) |
| `WITH_SEMANTIC` | `0` | `1` instala PyTorch CPU y FAISS (~1 GB más). El modelo (~460 MB) se descarga en la primera búsqueda semántica y se guarda en el volumen |

## Diferencias con la instalación nativa en Windows

- **OCR incluido** en la imagen; en Windows hay que instalar Tesseract aparte.
- **Rutas de datos:** `/data` dentro del volumen, en lugar de `data\` en la
  carpeta del proyecto. Para respaldar:
  `docker run --rm -v docusearch-data:/data -v "$PWD:/backup" python:3.12-slim tar czf /backup/respaldo.tgz -C /data .`
- **Modelo semántico:** se descarga dentro del volumen (`/data/hf-cache`).
- **Docker Desktop en Windows** necesita WSL 2 y más memoria. Si el objetivo
  es solo demostrar, la instalación nativa es más ligera.
- **RAG con Ollama:** el contenedor no puede llegar al Ollama del anfitrión
  por `127.0.0.1`, y DocuSearch solo acepta proveedores en loopback por
  privacidad. Con Docker, el RAG queda desactivado; úselo con la instalación
  nativa.

## Exponer en una red (no por defecto)

No cambie el puerto a `0.0.0.0`. Si hace falta acceso remoto, ponga delante un
proxy inverso con TLS en el anfitrión, defina `DOCUSEARCH_COOKIE_SECURE=true`
y siga [`seguridad.md`](seguridad.md). La imagen no se publica en ningún
registro.

## Verificación

El check de CI `docker-local`:

1. construye la imagen (sin publicarla);
2. arranca con Compose y espera `healthy`;
3. comprueba que el puerto solo escucha en `127.0.0.1`;
4. inicia sesión, carga un documento y lo encuentra con BM25; la preparación
   confirma el OCR;
5. reinicia, elimina y recrea el contenedor, y comprueba que el documento
   sigue en el volumen y que la imagen no contiene datos.

En el entorno donde se escribió esta entrega no había demonio de Docker, así
que la verificación real es la de ese check.
