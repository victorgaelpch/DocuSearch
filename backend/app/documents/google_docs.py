"""Importación de Google Docs **públicos** por enlace (DOC-22).

Un documento compartido como "cualquier persona con el enlace" se puede
exportar a DOCX sin credenciales::

    https://docs.google.com/document/d/<ID>/export?format=docx

Se descarga ese DOCX y se procesa con el lector DOCX existente. Los
documentos privados redirigen a la página de inicio de sesión de Google y se
rechazan con ``not_public``; importarlos requiere OAuth (pendiente).

Seguridad (SSRF):

* Solo se acepta ``https://docs.google.com/document/d/<ID>…``. La URL de
  descarga se **construye** a partir del ID validado; nunca se usa la URL del
  usuario tal cual.
* Las redirecciones solo pueden ir a ``docs.google.com`` o a
  ``*.googleusercontent.com`` por HTTPS.
* Tamaño máximo (el de las cargas) leído por bloques y tiempo límite.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .validation import UploadValidationError

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
EXPORT_URL = "https://docs.google.com/document/d/{doc_id}/export?format=docx"
CANONICAL_URL = "https://docs.google.com/document/d/{doc_id}/edit"
USER_AGENT = "DocuSearch-AI/0.2 (Google Docs public import)"
TIMEOUT_SECONDS = 30
READ_CHUNK = 64 * 1024

_DOC_ID = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
_PATH = re.compile(r"^/document(?:/u/\d+)?/d/([^/]+)")
_FILENAME_STAR = re.compile(r"filename\*\s*=\s*([^']*)''([^;]+)", re.IGNORECASE)
_FILENAME = re.compile(r'filename\s*=\s*"([^"]+)"', re.IGNORECASE)


class RemoteImportError(UploadValidationError):
    """Fallo al obtener el documento remoto (código y estado HTTP propios)."""


def parse_google_doc_url(url: str) -> str:
    """ID del documento de una URL de Google Docs, o ``invalid_url``."""
    try:
        parsed = urllib.parse.urlsplit((url or "").strip())
    except ValueError as exc:
        raise RemoteImportError("invalid_url", f"URL no válida: {exc}", 422) from exc
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "docs.google.com" or parsed.port not in (None, 443):
        raise RemoteImportError(
            "invalid_url", "solo se admiten enlaces https://docs.google.com/document/d/…", 422
        )
    match = _PATH.match(parsed.path)
    if not match or not _DOC_ID.match(match.group(1)):
        raise RemoteImportError("invalid_url", "el enlace no contiene un identificador de Google Docs válido", 422)
    return match.group(1)


def canonical_url(doc_id: str) -> str:
    return CANONICAL_URL.format(doc_id=doc_id)


def _allowed_redirect(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "docs.google.com" or host.endswith(".googleusercontent.com"))


def _is_login(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host in ("accounts.google.com", "accounts.youtube.com")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        if _is_login(newurl):
            raise RemoteImportError(
                "not_public",
                "el documento no es público: compártelo como 'cualquier persona con el enlace' o descárgalo como .docx",
                403,
            )
        if not _allowed_redirect(newurl):
            raise RemoteImportError("remote_error", f"redirección no permitida a {urllib.parse.urlsplit(newurl).hostname}", 502)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def filename_from_disposition(header: str | None, doc_id: str) -> str:
    """Nombre del archivo de ``Content-Disposition`` (siempre ``.docx``)."""
    name = None
    if header:
        star = _FILENAME_STAR.search(header)
        if star:
            name = urllib.parse.unquote(star.group(2).strip().strip('"'), encoding=star.group(1) or "utf-8")
        else:
            plain = _FILENAME.search(header)
            name = plain.group(1) if plain else None
    if not name:
        name = f"google-doc-{doc_id}.docx"
    if not name.lower().endswith(".docx"):
        name += ".docx"
    return name


@dataclass(frozen=True)
class RemoteDocument:
    doc_id: str
    filename: str
    data: bytes
    source_uri: str


Opener = Callable[[urllib.request.Request, float], Any]


def _default_open(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.build_opener(_SafeRedirect()).open(request, timeout=timeout)


def fetch_public_doc(url: str, *, max_bytes: int, open_url: Opener | None = None) -> RemoteDocument:
    """Descarga un Google Doc público como DOCX."""
    doc_id = parse_google_doc_url(url)
    request = urllib.request.Request(EXPORT_URL.format(doc_id=doc_id), headers={"User-Agent": USER_AGENT})
    try:
        response = (open_url or _default_open)(request, TIMEOUT_SECONDS)
    except RemoteImportError:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RemoteImportError("not_found", "Google Docs no encontró el documento", 404) from exc
        if exc.code in (401, 403):
            raise RemoteImportError("not_public", "el documento no es público", 403) from exc
        raise RemoteImportError("remote_error", f"Google Docs respondió {exc.code}", 502) from exc
    except TimeoutError as exc:
        raise RemoteImportError("remote_timeout", "Google Docs no respondió a tiempo", 504) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RemoteImportError("remote_error", f"no se pudo contactar con Google Docs: {exc}", 502) from exc

    with response:
        final_url = response.geturl() if hasattr(response, "geturl") else ""
        if final_url and _is_login(final_url):
            raise RemoteImportError("not_public", "el documento no es público", 403)
        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != DOCX_MIME:
            raise RemoteImportError(
                "not_public",
                f"Google Docs no devolvió un DOCX ({content_type or 'sin tipo'}); ¿el documento es público?",
                403,
            )
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise RemoteImportError("file_too_large", "el documento exportado supera el tamaño máximo", 413)
        chunks: list[bytes] = []
        received = 0
        while chunk := response.read(READ_CHUNK):
            received += len(chunk)
            if received > max_bytes:
                raise RemoteImportError("file_too_large", "el documento exportado supera el tamaño máximo", 413)
            chunks.append(chunk)
        filename = filename_from_disposition(response.headers.get("Content-Disposition"), doc_id)
    return RemoteDocument(doc_id=doc_id, filename=filename, data=b"".join(chunks), source_uri=canonical_url(doc_id))
