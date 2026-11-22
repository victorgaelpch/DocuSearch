# Autenticación local (DOC-25)

DocuSearch se entrega en **modo local monousuario**: una instalación en
`127.0.0.1`, con como máximo una cuenta de **Administrador** y una de
**Usuario de consulta**. No hay registro de cuentas ni documentos por
propietario: **no es un sistema multiusuario**.

| Rol | Permisos |
| --- | --- |
| Administrador (`admin`) | Consultar + cargar, importar, editar, eliminar y reindexar |
| Usuario (`user`) | Listar, ver, descargar y buscar los documentos privados |
| Sin sesión | `/health`, `/auth/*`, búsqueda en corpus públicos (`wikipedia_es`) |

## Configurar las cuentas

No existe contraseña por defecto: **sin hash configurado no hay cuenta** y
los endpoints privados responden 401.

```powershell
# 1. Generar el hash (pide la contraseña sin mostrarla; mínimo 12 caracteres)
python -m backend.app.cli hash-password
# 2. Guardarlo en la sesión de PowerShell (o en .env, que no se versiona)
$env:DOCUSEARCH_ADMIN_PASSWORD_HASH = "scrypt$16384$8$1$...$..."
# 3. (opcional) cuenta de solo consulta
$env:DOCUSEARCH_USER_PASSWORD_HASH = "scrypt$..."
```

En PowerShell use comillas simples o dobles con cuidado: `$` dentro de
comillas dobles se interpreta como variable. Con comillas simples
(`'scrypt$16384$…'`) se guarda literal.

| Variable | Por defecto | Uso |
| --- | --- | --- |
| `DOCUSEARCH_ADMIN_USERNAME` | `admin` | Nombre de la cuenta de Administrador |
| `DOCUSEARCH_ADMIN_PASSWORD_HASH` | — | Hash scrypt; sin él no hay administrador |
| `DOCUSEARCH_USER_USERNAME` | `usuario` | Nombre de la cuenta de consulta |
| `DOCUSEARCH_USER_PASSWORD_HASH` | — | Hash scrypt; opcional |
| `DOCUSEARCH_SESSION_IDLE_MINUTES` | `30` | Cierre por inactividad |
| `DOCUSEARCH_SESSION_MAX_HOURS` | `8` | Duración máxima de una sesión |
| `DOCUSEARCH_COOKIE_SECURE` | `false` | `true` si se sirve detrás de HTTPS |

Un hash mal copiado hace que el servidor no arranque (error explícito), en
lugar de dejar la cuenta inaccesible sin aviso.

## Diseño

- **Contraseñas:** `hashlib.scrypt` (biblioteca estándar; n=2¹⁴, r=8, p=1,
  sal de 16 bytes). Verificación en tiempo constante. La contraseña en claro
  no se guarda, no se registra y no se devuelve.
- **Sesión:** cookie `docusearch_session` con `HttpOnly`, `SameSite=Strict`
  y `Path=/` (`Secure` configurable). El servidor guarda en memoria solo el
  SHA-256 del identificador. Cada inicio de sesión genera un identificador
  nuevo (evita fijación de sesión).
- **Caducidad:** por inactividad (30 min) y absoluta (8 h). `POST
  /auth/logout` borra la sesión en el servidor: la cookie anterior deja de
  servir. Reiniciar el servidor cierra todas las sesiones.
- **CSRF:** toda mutación autenticada exige la cabecera `X-CSRF-Token` con el
  token de la sesión (lo devuelven `/auth/login` y `/auth/me`) y rechaza
  `Origin` de otro sitio o `Sec-Fetch-Site: cross-site`. El login también
  comprueba el origen.
- **Intentos:** 5 fallos en 5 minutos por IP bloquean el login con 429 y
  `Retry-After`. Un usuario inexistente y una contraseña incorrecta dan la
  misma respuesta.
- **Nunca** se aceptan credenciales por query string ni se guardan tokens en
  `localStorage`.

## Endpoints

| Método | Ruta | Respuesta |
| --- | --- | --- |
| `POST` | `/auth/login` `{"username", "password"}` | 200 con rol, `csrf_token` y caducidad; 401 `invalid_credentials` / `auth_not_configured`; 403 origen; 429 |
| `POST` | `/auth/logout` (cabecera `X-CSRF-Token`) | 204 |
| `GET` | `/auth/me` | Sesión actual o `{"authenticated": false}` |

Errores comunes en los demás endpoints: 401 `not_authenticated` (sin
sesión o expirada), 403 `forbidden` (rol Usuario intentando mutar), 403
`csrf_failed`.

## Ejemplo con PowerShell

```powershell
$s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$login = Invoke-RestMethod -Method Post http://127.0.0.1:8000/auth/login -WebSession $s `
  -ContentType "application/json" -Body '{"username":"admin","password":"<su contraseña>"}'
Invoke-RestMethod http://127.0.0.1:8000/documents -WebSession $s
curl.exe -b "docusearch_session=..." -H "X-CSRF-Token: $($login.csrf_token)" -F "file=@C:\ruta\a.pdf" http://127.0.0.1:8000/documents
```

## Límites

- Apto para `127.0.0.1`. Para exponerlo en una red hace falta HTTPS (proxy
  inverso), `DOCUSEARCH_COOKIE_SECURE=true` y revisar `docs/seguridad.md`
  (DOC-32).
- Sesiones en memoria: no se comparten entre procesos (`uvicorn --workers 1`).
- El límite de intentos es por IP del cliente tal como la ve el servidor;
  detrás de un proxy todas las peticiones compartirían IP.
