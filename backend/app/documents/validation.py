"""Validación de archivos cargados antes de procesarlos (DOC-04).

Comprueba, sin ejecutar ni interpretar el contenido más allá de lo necesario:

* nombre de archivo seguro (se descarta cualquier ruta enviada por el cliente);
* extensión admitida;
* tamaño (vacío y máximo configurable);
* **tipo real** por firma de bytes, independiente del ``Content-Type`` del
  cliente: PDF (``%PDF-``), DOCX (ZIP con partes de Word y sin macros) o texto
  plano (sin bytes nulos ni firmas binarias conocidas);
* DOCX: límites de entradas y tamaño descomprimido (protección frente a
  "ZIP bombs").
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import PurePath

from .readers import DOCX_MIME, PDF_MIME, SUPPORTED_EXTENSIONS, TXT_MIME

MAX_FILENAME_LENGTH = 255
MAX_DOCX_ENTRIES = 2000

_BINARY_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "PDF"),
    (b"PK\x03\x04", "ZIP/Office"),
    (b"MZ", "ejecutable de Windows"),
    (b"\x7fELF", "ejecutable ELF"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "documento OLE (.doc/.xls)"),
    (b"\x89PNG", "imagen PNG"),
    (b"\xff\xd8\xff", "imagen JPEG"),
    (b"GIF8", "imagen GIF"),
    (b"\x1f\x8b", "archivo gzip"),
    (b"Rar!", "archivo RAR"),
    (b"7z\xbc\xaf", "archivo 7z"),
)
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
_WINDOWS_RESERVED = re.compile(r"^(con|prn|aux|nul|com\d|lpt\d)$", re.IGNORECASE)


class UploadValidationError(ValueError):
    """Archivo rechazado; ``code`` y ``status_code`` sirven para la respuesta HTTP."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    extension: str
    mime_type: str
    data: bytes


def sanitize_filename(raw: str | None) -> str:
    """Nombre seguro para metadatos y descargas: sin rutas ni caracteres de control."""
    if not raw:
        raise UploadValidationError("invalid_filename", "falta el nombre del archivo")
    name = raw.replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFC", name)
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = name.strip().strip(".").strip()
    stem = PurePath(name).stem
    if not name or not stem or _WINDOWS_RESERVED.match(stem):
        raise UploadValidationError("invalid_filename", "nombre de archivo no válido")
    if len(name) > MAX_FILENAME_LENGTH:
        suffix = PurePath(name).suffix[:16]
        name = stem[: MAX_FILENAME_LENGTH - len(suffix)] + suffix
    return name


def _detect_pdf(data: bytes) -> None:
    if b"%PDF-" not in data[:1024]:
        raise UploadValidationError(
            "content_mismatch", "el contenido no corresponde a un PDF", 415
        )


def _detect_docx(data: bytes, max_uncompressed: int) -> None:
    if not data.startswith(b"PK\x03\x04"):
        raise UploadValidationError(
            "content_mismatch", "el contenido no corresponde a un archivo DOCX", 415
        )
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ENTRIES:
                raise UploadValidationError(
                    "docx_too_complex", "el DOCX contiene demasiadas partes internas", 413
                )
            total = sum(entry.file_size for entry in entries)
            if total > max_uncompressed:
                raise UploadValidationError(
                    "docx_too_large",
                    "el DOCX descomprimido supera el límite permitido",
                    413,
                )
            names = {entry.filename for entry in entries}
    except zipfile.BadZipFile as exc:
        raise UploadValidationError("corrupt_file", "el DOCX está dañado (ZIP inválido)") from exc
    if "[Content_Types].xml" not in names or "word/document.xml" not in names:
        raise UploadValidationError(
            "content_mismatch", "el ZIP no contiene un documento de Word (.docx)", 415
        )
    if "word/vbaProject.bin" in names:
        raise UploadValidationError(
            "macros_not_allowed", "no se admiten documentos con macros", 415
        )


def _detect_txt(data: bytes) -> None:
    if data.startswith(_UTF16_BOMS):
        return
    for signature, label in _BINARY_SIGNATURES:
        if data.startswith(signature):
            raise UploadValidationError(
                "content_mismatch", f"el archivo .txt contiene un {label}", 415
            )
    if b"\x00" in data[:8192]:
        raise UploadValidationError(
            "content_mismatch", "el archivo .txt parece binario", 415
        )


def validate_upload(
    filename: str | None,
    data: bytes,
    *,
    max_bytes: int,
    max_docx_uncompressed_bytes: int,
) -> ValidatedUpload:
    """Valida nombre, extensión, tamaño y tipo real. Lanza ``UploadValidationError``."""
    name = sanitize_filename(filename)
    extension = PurePath(name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UploadValidationError(
            "unsupported_format",
            f"formato no admitido: {extension or '(sin extensión)'}; "
            f"se aceptan {', '.join(SUPPORTED_EXTENSIONS)}",
            415,
        )
    if not data:
        raise UploadValidationError("empty_file", "el archivo está vacío", 400)
    if len(data) > max_bytes:
        raise UploadValidationError(
            "file_too_large",
            f"el archivo supera el máximo de {max_bytes // (1024 * 1024)} MB",
            413,
        )
    if extension == ".pdf":
        _detect_pdf(data)
        mime = PDF_MIME
    elif extension == ".docx":
        _detect_docx(data, max_docx_uncompressed_bytes)
        mime = DOCX_MIME
    else:
        _detect_txt(data)
        mime = TXT_MIME
    return ValidatedUpload(filename=name, extension=extension, mime_type=mime, data=data)
