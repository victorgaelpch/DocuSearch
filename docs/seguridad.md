# Seguridad de la aplicación web (DOC-32)

**Alcance:** DocuSearch v1.0 está pensado para ejecutarse en `127.0.0.1` en
una computadora personal, con una cuenta de Administrador y, opcionalmente,
una de consulta (ver `docs/autenticacion.md`). Que las pruebas pasen **no
significa que el servidor sea seguro para Internet**: para eso hacen falta los
pasos de la sección "Exponer en una red".

## Modelo de amenazas

| Amenaza | Control | Evidencia |
| --- | --- | --- |
| Acceso anónimo a documentos privados | Sesión obligatoria en `/documents/*`, `/search?collection=user`, `/admin/*`; comprobada en el servidor en cada endpoint | `tests/test_auth.py`, `tests/test_security.py` |
| Escalada de Usuario a Administrador | Rol comprobado en el servidor (403); la interfaz solo oculta | `test_reader_can_consult_but_not_mutate`, `test_validation_and_permissions` |
| CSRF | Cookie `SameSite=Strict` + cabecera `X-CSRF-Token` + `Origin`/`Sec-Fetch-Site` | `test_mutation_without_csrf_is_rejected`, E2E `test_cross_site_form_post_cannot_upload` |
| XSS por títulos, nombres o texto de documentos | La interfaz construye el DOM con nodos de texto (sin `innerHTML`, prohibido por prueba); CSP `script-src 'self'` sin `unsafe-inline` | `tests/test_web.py`, E2E `test_malicious_title_is_shown_as_text_everywhere`, `test_opens_requested_chunk_highlighted_and_navigates` |
| Ejecución de contenido de DOCX/TXT | No se renderizan: solo texto plano. La vista previa en línea existe solo para PDF, con `nosniff` | `test_preview_rejects_non_pdf` |
| Path traversal | `OriginalStore.resolve` rechaza rutas fuera del almacén; `doc_id` con patrón estricto; `StaticFiles` solo sirve `frontend/assets` | `test_traversal_attempts_are_rejected`, `test_malicious_filenames_never_escape_storage` |
| ZIP bomb DOCX, PDF corrupto, tipo falso | Límite de tamaño descomprimido, validación del tipo real por contenido | `tests/test_upload_validation.py`, E2E de carga |
| SSRF en la importación | La URL de descarga se construye con el ID validado; solo redirecciones HTTPS a dominios de Google | `tests/test_google_docs_import.py` |
| Agotar disco o memoria con cargas | Mutaciones privadas sin sesión → 401 **antes de leer el cuerpo**; `Content-Length` obligatorio (411) y con máximo (413) | `test_anonymous_mutation_is_rejected_before_reading_body`, `test_declared_oversize_upload_is_rejected` |
| Fuerza bruta de contraseñas | 5 fallos en 5 min por IP → 429; respuesta idéntica para usuario inexistente | `test_login_rate_limit` |
| Robo de sesión | Cookie `HttpOnly`, identificador de 256 bits, solo su hash en memoria, rotación al iniciar sesión, caducidad | `test_logout_invalidates_session`, `test_login_rotates_session_token` |
| Fuga por caché del navegador | `Cache-Control: no-store` en `/documents`, `/search`, `/auth`, `/admin` | `test_private_responses_are_not_cached` |
| Clickjacking | `X-Frame-Options: DENY` y `frame-ancestors 'none'`; la vista previa PDF solo se enmarca en el mismo origen | `test_security_headers_everywhere`, `test_pdf_preview_keeps_its_frame_policy` |
| Datos de un documento borrado en índices | Purga de caché léxica y vectores FAISS al eliminar | `test_delete_removes_document_everywhere` |
| Secretos o datos privados en Git | `.gitignore` de `data/`, `.env`; prueba que revisa los archivos versionados; GitGuardian en los PR | `test_no_secrets_or_private_data_tracked` |
| Inyección de instrucciones o fuga de documentos vía RAG (v1.1) | Fragmentos delimitados como datos, delimitadores neutralizados, sin herramientas; solo proveedor en `127.0.0.1` sin proxy; citas validadas contra lo recuperado | `tests/test_rag.py` |
| Contraseñas en registros o respuestas | Ninguna ruta registra el cuerpo del login; solo se guarda el hash scrypt | `test_password_never_appears_in_logs_or_responses` |

## Cabeceras

Todas las respuestas llevan `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, `Permissions-Policy` restrictiva y
`Cross-Origin-Opener-Policy`/`Cross-Origin-Resource-Policy: same-origin`.
Las de la aplicación añaden:

```text
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:;
  font-src 'self'; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none';
  form-action 'self'; frame-ancestors 'none'
X-Frame-Options: DENY
```

Excepciones documentadas:

- `/documents/{id}/content` (vista previa PDF): `X-Frame-Options: SAMEORIGIN` y
  `frame-ancestors 'self'`, para que el visor la muestre en un `<iframe>`.
- `/docs` y `/redoc` (Swagger/ReDoc de FastAPI) no llevan CSP porque cargan
  sus recursos de `cdn.jsdelivr.net`. **Sin conexión a Internet, `/docs` no
  se muestra**; la aplicación web y la API funcionan igual.

## Riesgos y límites conocidos

- **HTTP sin cifrar.** En `127.0.0.1` el tráfico no sale de la computadora. En
  una red, la contraseña y la cookie viajarían en claro.
- **Sesiones en memoria** y límite de intentos por IP: con varios workers o
  detrás de un proxy, el límite y las sesiones no se comparten.
- **Un solo usuario por rol**, sin auditoría de acciones ni recuperación de
  contraseña.
- **PDF en el visor del navegador:** el PDF se muestra con el visor del
  navegador (PDFium en Chrome/Edge), que es la superficie de ataque de
  cualquier PDF que se abre localmente.
- **Dependencias:** PyMuPDF, python-docx, spaCy y Tesseract procesan archivos
  no confiables; manténgalos actualizados.
- No se ha hecho una auditoría externa ni pruebas de penetración.

## Docker (v1.1)

`compose.yaml` publica el puerto solo en `127.0.0.1`, ejecuta como usuario sin
privilegios con el sistema de archivos de solo lectura, `cap_drop: ALL` y
`no-new-privileges`, y guarda los datos en un volumen, nunca en la imagen. Ver
`docs/docker.md`.

## Exponer en una red (no recomendado para la entrega)

Si alguna vez se necesita acceso desde otra máquina:

1. Mantener uvicorn en `127.0.0.1` y poner delante un proxy inverso con TLS
   (por ejemplo Caddy: `docusearch.ejemplo.local { reverse_proxy 127.0.0.1:8000 }`).
2. `DOCUSEARCH_COOKIE_SECURE=true` para que la cookie solo viaje por HTTPS.
3. Un solo worker (`--workers 1`): las sesiones y las tareas viven en memoria.
4. Ajustar `DOCUSEARCH_MAX_UPLOAD_MB` y el límite de cuerpo del proxy.
5. Restringir el acceso por red (firewall o VPN) además de la contraseña.
6. Revisar el límite de intentos: detrás del proxy todas las peticiones
   comparten IP; configure `--proxy-headers` y `--forwarded-allow-ips` en
   uvicorn solo con un proxy de confianza.
