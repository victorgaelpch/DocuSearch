"""Lectores de PDF digital, Word ``.docx`` y ``.txt`` (DOC-03).

Cada lector recibe los bytes del archivo y devuelve un ``ExtractionResult`` con
el texto completo, sus secciones (páginas en PDF, párrafos en DOCX, el texto
entero en TXT) con offsets y los metadatos útiles para el índice y la interfaz.

Errores controlados:

* ``UnsupportedFormatError``: extensión no admitida (no se intenta leer).
* ``EmptyFileError``: archivo de 0 bytes.
* ``CorruptFileError``: contenido dañado, cifrado o que no corresponde al formato.

``extract_document`` convierte los dos últimos en un resultado con estado
``failed`` y mensaje de error, para registrarlos por archivo sin interrumpir
un lote. Un PDF sin capa de texto devuelve ``needs_ocr`` (OCR: DOC-23).
"""

from __future__ import annotations

import codecs
import io
import zipfile
from pathlib import PurePath
from typing import Any, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    DEFAULT_COLLECTION,
    Document,
    ExtractionStatus,
    SourceType,
    compute_sha256,
    make_document_id,
)
from .storage import build_storage_path

SECTION_SEPARATOR = "\n\n"
"""Separador entre páginas/párrafos en el texto completo."""

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TXT_MIME = "text/plain"


class ExtractionError(Exception):
    """Error base de extracción."""


class UnsupportedFormatError(ExtractionError):
    """Formato no admitido por los lectores del MVP."""


class EmptyFileError(ExtractionError):
    """El archivo no tiene contenido."""


class CorruptFileError(ExtractionError):
    """El archivo está dañado, cifrado o no corresponde a su extensión."""


class TextSection(BaseModel):
    """Unidad de texto con su posición en el texto completo."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    text: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    page_number: Optional[int] = Field(default=None, ge=1)


class ExtractionResult(BaseModel):
    """Texto y metadatos extraídos de un archivo."""

    model_config = ConfigDict(extra="forbid")

    filename: str
    extension: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    sha256: str
    title: str
    status: ExtractionStatus
    text: str = ""
    sections: list[TextSection] = Field(default_factory=list)
    page_count: Optional[int] = Field(default=None, ge=0)
    error: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    def page_for_offset(self, offset: int) -> Optional[int]:
        """Página que contiene el offset dado (``None`` si no hay paginación)."""
        for section in self.sections:
            if section.page_number is not None and section.char_start <= offset < max(
                section.char_end, section.char_start + 1
            ):
                return section.page_number
        return None


class _ReadOutput(BaseModel):
    """Salida interna de un lector antes de añadir hash, tamaño y estado."""

    sections: list[tuple[str, Optional[int]]]
    page_count: Optional[int] = None
    title: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    no_text_status: ExtractionStatus = ExtractionStatus.EMPTY


class DocumentReader(Protocol):
    """Interfaz común de los lectores por formato."""

    extensions: tuple[str, ...]
    mime_type: str

    def read(self, data: bytes) -> _ReadOutput: ...


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


class PdfReader:
    """PDF con capa de texto mediante PyMuPDF; una sección por página."""

    extensions = (".pdf",)
    mime_type = PDF_MIME

    def read(self, data: bytes) -> _ReadOutput:
        if b"%PDF-" not in data[:1024]:
            raise CorruptFileError("el archivo no tiene cabecera PDF válida")
        import pymupdf

        try:
            document = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:  # PyMuPDF lanza FileDataError/RuntimeError
            raise CorruptFileError(f"PDF dañado o ilegible: {exc}") from exc
        try:
            if document.needs_pass:
                raise CorruptFileError("PDF protegido con contraseña; no se puede extraer")
            sections: list[tuple[str, Optional[int]]] = []
            empty_pages: list[int] = []
            try:
                for number, page in enumerate(document, start=1):
                    text = _normalize_newlines(page.get_text("text")).strip()
                    if not text:
                        empty_pages.append(number)
                    sections.append((text, number))
            except Exception as exc:
                raise CorruptFileError(f"error al leer páginas del PDF: {exc}") from exc
            info = document.metadata or {}
            page_count = document.page_count
        finally:
            document.close()

        warnings = []
        if empty_pages and len(empty_pages) < page_count:
            warnings.append(
                "páginas sin texto (posible imagen escaneada, requiere OCR): "
                + ", ".join(map(str, empty_pages))
            )
        metadata = {
            key: info[key].strip()
            for key in ("author", "subject", "creator", "producer")
            if isinstance(info.get(key), str) and info[key].strip()
        }
        if empty_pages:
            metadata["pages_without_text"] = empty_pages
        return _ReadOutput(
            sections=sections,
            page_count=page_count,
            title=(info.get("title") or "").strip() or None,
            warnings=warnings,
            metadata=metadata,
            no_text_status=ExtractionStatus.NEEDS_OCR if page_count else ExtractionStatus.EMPTY,
        )


class DocxReader:
    """Word ``.docx`` con python-docx; una sección por párrafo o fila de tabla."""

    extensions = (".docx",)
    mime_type = DOCX_MIME

    def read(self, data: bytes) -> _ReadOutput:
        if not data.startswith(b"PK"):
            raise CorruptFileError("el archivo no es un paquete DOCX (ZIP) válido")
        import docx
        from docx.opc.exceptions import PackageNotFoundError

        try:
            document = docx.Document(io.BytesIO(data))
        except (zipfile.BadZipFile, PackageNotFoundError, KeyError, ValueError) as exc:
            raise CorruptFileError(f"DOCX dañado o no válido: {exc}") from exc
        except Exception as exc:  # XML mal formado, etc.
            raise CorruptFileError(f"DOCX ilegible: {exc}") from exc

        from docx.table import Table

        sections: list[tuple[str, Optional[int]]] = []
        paragraph_count = 0
        table_rows = 0
        try:
            # Orden real del cuerpo: párrafos y tablas intercalados.
            for block in document.iter_inner_content():
                if isinstance(block, Table):
                    for row in block.rows:
                        cells: list[str] = []
                        for cell in row.cells:
                            value = _normalize_newlines(cell.text).strip()
                            if value and (not cells or cells[-1] != value):  # celdas combinadas
                                cells.append(value)
                        if cells:
                            sections.append((" | ".join(cells), None))
                            table_rows += 1
                else:
                    text = _normalize_newlines(block.text).strip()
                    if text:
                        sections.append((text, None))
                        paragraph_count += 1
        except Exception as exc:
            raise CorruptFileError(f"error al recorrer el contenido del DOCX: {exc}") from exc

        core = document.core_properties
        metadata: dict[str, Any] = {"paragraphs": paragraph_count, "table_rows": table_rows}
        if core.author:
            metadata["author"] = core.author
        warnings = []
        if document.inline_shapes and not sections:
            warnings.append("el documento solo contiene imágenes; requiere OCR")
        return _ReadOutput(
            sections=sections,
            title=(core.title or "").strip() or None,
            warnings=warnings,
            metadata=metadata,
        )


class TxtReader:
    """Texto plano con decodificación controlada.

    Orden: BOM (UTF-8/UTF-16) → UTF-8 estricto → Windows-1252 (con aviso).
    Se rechazan archivos binarios (bytes nulos sin BOM UTF-16).
    """

    extensions = (".txt",)
    mime_type = TXT_MIME

    def read(self, data: bytes) -> _ReadOutput:
        text, encoding, warnings = self._decode(data)
        text = _normalize_newlines(text).strip()
        return _ReadOutput(
            sections=[(text, None)] if text else [],
            warnings=warnings,
            metadata={"encoding": encoding},
        )

    @staticmethod
    def _decode(data: bytes) -> tuple[str, str, list[str]]:
        boms = (
            (codecs.BOM_UTF8, "utf-8-sig"),
            (codecs.BOM_UTF16_LE, "utf-16"),
            (codecs.BOM_UTF16_BE, "utf-16"),
        )
        for bom, encoding in boms:
            if data.startswith(bom):
                try:
                    return data.decode(encoding), encoding, []
                except UnicodeDecodeError as exc:
                    raise CorruptFileError(f"texto {encoding} inválido: {exc}") from exc
        if b"\x00" in data:
            raise CorruptFileError("el archivo contiene bytes nulos; parece binario, no texto")
        try:
            return data.decode("utf-8"), "utf-8", []
        except UnicodeDecodeError:
            pass
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise CorruptFileError("codificación de texto no reconocida (ni UTF-8 ni Windows-1252)") from exc
        return text, "cp1252", ["no es UTF-8; se decodificó como Windows-1252"]


_READERS: tuple[DocumentReader, ...] = (PdfReader(), DocxReader(), TxtReader())

SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(
    extension for reader in _READERS for extension in reader.extensions
)


def get_reader(filename: str) -> DocumentReader:
    """Lector según la extensión del archivo (sin distinguir mayúsculas)."""
    extension = PurePath(filename).suffix.lower()
    for reader in _READERS:
        if extension in reader.extensions:
            return reader
    raise UnsupportedFormatError(
        f"formato no admitido: {extension or '(sin extensión)'}; "
        f"se aceptan {', '.join(SUPPORTED_EXTENSIONS)}"
    )


def _assemble(sections: list[tuple[str, Optional[int]]]) -> tuple[str, list[TextSection]]:
    parts: list[str] = []
    result: list[TextSection] = []
    offset = 0
    for index, (text, page) in enumerate(sections):
        if index:
            parts.append(SECTION_SEPARATOR)
            offset += len(SECTION_SEPARATOR)
        parts.append(text)
        result.append(
            TextSection(
                index=index,
                text=text,
                char_start=offset,
                char_end=offset + len(text),
                page_number=page,
            )
        )
        offset += len(text)
    return "".join(parts), result


def extract_document(data: bytes, filename: str) -> ExtractionResult:
    """Extrae texto y metadatos de un archivo PDF, DOCX o TXT.

    Lanza ``UnsupportedFormatError`` si la extensión no se admite. Los archivos
    vacíos o dañados no lanzan excepción: devuelven un resultado con estado
    ``empty``/``failed`` y el motivo en ``error``.
    """
    reader = get_reader(filename)
    name = PurePath(filename).name
    base = dict(
        filename=name,
        extension=PurePath(name).suffix.lower(),
        mime_type=reader.mime_type,
        size_bytes=len(data),
        sha256=compute_sha256(data),
        title=PurePath(name).stem or name,
    )
    try:
        if not data:
            raise EmptyFileError("el archivo está vacío (0 bytes)")
        output = reader.read(data)
    except EmptyFileError as exc:
        return ExtractionResult(**base, status=ExtractionStatus.EMPTY, error=str(exc))
    except CorruptFileError as exc:
        return ExtractionResult(**base, status=ExtractionStatus.FAILED, error=str(exc))

    text, sections = _assemble(output.sections)
    has_text = bool(text.strip())
    if output.title:
        base["title"] = output.title[:500]
    return ExtractionResult(
        **base,
        status=ExtractionStatus.EXTRACTED if has_text else output.no_text_status,
        text=text,
        sections=sections,
        page_count=output.page_count,
        error=None if has_text else "no se encontró texto extraíble",
        warnings=output.warnings,
        metadata=output.metadata,
    )


def build_document(
    result: ExtractionResult,
    *,
    collection: str = DEFAULT_COLLECTION,
    source_type: SourceType = SourceType.UPLOAD,
    source_uri: str | None = None,
) -> Document:
    """Crea el ``Document`` (DOC-02) con los metadatos de la extracción.

    El original debe guardarse con ``OriginalStore`` en ``storage_path``.
    """
    doc_id = make_document_id(result.sha256, collection)
    extra: dict[str, Any] = dict(result.metadata)
    if result.warnings:
        extra["warnings"] = list(result.warnings)
    return Document(
        doc_id=doc_id,
        collection=collection,
        source_type=source_type,
        title=result.title,
        original_filename=result.filename,
        mime_type=result.mime_type,
        size_bytes=result.size_bytes,
        sha256=result.sha256,
        storage_path=build_storage_path(doc_id, result.extension, collection),
        source_uri=source_uri,
        extraction_status=result.status,
        extraction_error=result.error[:2000] if result.error else None,
        page_count=result.page_count,
        extra=extra,
    )
