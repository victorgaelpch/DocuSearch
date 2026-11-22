# Frontend

Interfaz web de DocuSearch (DOC-26): HTML, CSS y JavaScript (módulos ES)
servidos por FastAPI en el mismo origen que la API. No requiere Node, CDN ni
compilación.

| Ruta | Contenido |
| --- | --- |
| `index.html` | Estructura de la página; se sirve en `GET /` |
| `assets/css/app.css` | Estilos (paleta, tipografía del sistema, diseño responsive) |
| `assets/js/app.js` | Arranque: sesión, navegación y enrutador |
| `assets/js/api.js` | Cliente de la API: cookie de sesión, token CSRF en memoria, errores |
| `assets/js/dom.js` | Construcción segura del DOM (sin `innerHTML`) |
| `assets/js/router.js` | Rutas por hash (`#/ruta/:param`) y foco accesible |
| `assets/js/views/` | Una vista por sección; `views/index.js` las registra |

Reglas:

- El texto de documentos y de la API se inserta siempre como nodos de texto
  (`textContent`), nunca con `innerHTML`.
- Sin dependencias externas: las fuentes son del sistema (Palatino/Segoe UI
  en Windows) y no hay peticiones fuera de `127.0.0.1`.
- La sesión viaja en una cookie `HttpOnly`; el token CSRF se guarda solo en
  memoria. Nada se guarda en `localStorage`.
- La interfaz oculta lo que un rol no puede hacer, pero los permisos los
  comprueba siempre el servidor.

Para probarla: inicie `python -m uvicorn backend.app.main:app` y abra
http://127.0.0.1:8000/.
