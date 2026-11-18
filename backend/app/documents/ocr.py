"""OCR de páginas de PDF escaneados con Tesseract (DOC-23).

Las páginas de un PDF sin capa de texto (``needs_ocr``) se rasterizan y se
reconocen con Tesseract a través de PyMuPDF (``Page.get_textpage_ocr``).
Tesseract es un programa del sistema (licencia Apache-2.0), no un paquete de
Python: si no está instalado, el OCR se desactiva y el comportamiento es el
de v0.1 (el documento queda como ``needs_ocr``).

Configuración (variables de entorno):

* ``DOCUSEARCH_OCR``: ``auto`` (por defecto, usa Tesseract si lo encuentra) u
  ``off``.
* ``DOCUSEARCH_OCR_LANG``: idiomas de Tesseract, por defecto ``spa+eng``. Se
  usan los que estén instalados; si falta alguno se registra un aviso.
* ``DOCUSEARCH_OCR_DPI``: resolución de rasterizado, por defecto 300.
* ``DOCUSEARCH_OCR_MAX_PAGES``: máximo de páginas a reconocer por documento
  (por defecto 50) para acotar el tiempo de una carga.
* ``DOCUSEARCH_TESSDATA`` o ``TESSDATA_PREFIX``: carpeta ``tessdata``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OCR_MODE_ENV = "DOCUSEARCH_OCR"
OCR_LANG_ENV = "DOCUSEARCH_OCR_LANG"
OCR_DPI_ENV = "DOCUSEARCH_OCR_DPI"
OCR_MAX_PAGES_ENV = "DOCUSEARCH_OCR_MAX_PAGES"
TESSDATA_ENV = "DOCUSEARCH_TESSDATA"
DEFAULT_LANGUAGES = "spa+eng"
DEFAULT_DPI = 300
DEFAULT_MAX_PAGES = 50

_COMMON_TESSDATA = (
    Path(r"C:\Program Files\Tesseract-OCR\tessdata"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tessdata"),
    Path("/usr/share/tesseract-ocr/5/tessdata"),
    Path("/usr/share/tesseract-ocr/4.00/tessdata"),
    Path("/usr/share/tessdata"),
    Path("/opt/homebrew/share/tessdata"),
    Path("/usr/local/share/tessdata"),
)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} debe ser un entero, se recibió {raw!r}") from exc
    if value < 1:
        raise ValueError(f"{name} debe ser mayor que 0")
    return value


def find_tessdata() -> Path | None:
    """Carpeta ``tessdata`` con al menos un idioma, o ``None``."""
    candidates: list[Path] = []
    for env in (TESSDATA_ENV, "TESSDATA_PREFIX"):
        if os.environ.get(env):
            base = Path(os.environ[env])
            candidates += [base, base / "tessdata"]
    executable = shutil.which("tesseract")
    if executable:
        candidates.append(Path(executable).resolve().parent / "tessdata")
    candidates += list(_COMMON_TESSDATA)
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("*.traineddata")):
            return candidate
    return None


@dataclass(frozen=True)
class OcrConfig:
    enabled: bool = True
    languages: str = DEFAULT_LANGUAGES
    dpi: int = DEFAULT_DPI
    max_pages: int = DEFAULT_MAX_PAGES

    @classmethod
    def from_env(cls) -> "OcrConfig":
        mode = (os.environ.get(OCR_MODE_ENV) or "auto").strip().lower()
        if mode not in ("auto", "off"):
            raise ValueError(f"{OCR_MODE_ENV} debe ser 'auto' u 'off'")
        return cls(
            enabled=mode == "auto",
            languages=(os.environ.get(OCR_LANG_ENV) or DEFAULT_LANGUAGES).strip(),
            dpi=_int_env(OCR_DPI_ENV, DEFAULT_DPI),
            max_pages=_int_env(OCR_MAX_PAGES_ENV, DEFAULT_MAX_PAGES),
        )


@dataclass
class OcrOutcome:
    """Resultado del OCR de un documento."""

    texts: dict[int, str] = field(default_factory=dict)  # página → texto
    language: str = ""
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def metadata(self, engine: dict[str, Any]) -> dict[str, Any]:
        return {
            **engine,
            "language": self.language,
            "pages": sorted(p for p, t in self.texts.items() if t.strip()),
            "seconds": round(self.seconds, 2),
        }


class TesseractOcr:
    """Reconocedor de páginas con Tesseract vía PyMuPDF."""

    def __init__(self, tessdata: Path, config: OcrConfig) -> None:
        self.tessdata = tessdata
        self.config = config

    @property
    def available_languages(self) -> list[str]:
        return sorted(p.stem for p in self.tessdata.glob("*.traineddata") if p.stem != "osd")

    def resolve_language(self) -> tuple[str, list[str]]:
        """Idiomas pedidos que están instalados y avisos por los que faltan."""
        requested = [lang for lang in self.config.languages.split("+") if lang]
        available = set(self.available_languages)
        usable = [lang for lang in requested if lang in available]
        missing = [lang for lang in requested if lang not in available]
        warnings = []
        if missing:
            warnings.append(
                f"OCR: idioma(s) no instalado(s) en Tesseract: {', '.join(missing)}; "
                "la precisión puede ser menor (ver docs/lectores.md)"
            )
        if not usable:
            fallback = "eng" if "eng" in available else (sorted(available)[0] if available else "")
            usable = [fallback] if fallback else []
        return "+".join(usable), warnings

    @property
    def engine(self) -> dict[str, Any]:
        return {"engine": "tesseract", "version": tesseract_version(self.tessdata), "dpi": self.config.dpi}

    def recognize(self, document: Any, pages: list[int]) -> OcrOutcome:
        """Reconoce las ``pages`` (numeradas desde 1) de un ``pymupdf.Document``."""
        language, warnings = self.resolve_language()
        outcome = OcrOutcome(language=language, warnings=warnings)
        if not language:
            outcome.warnings.append("OCR: Tesseract no tiene ningún idioma instalado")
            return outcome
        selected = pages[: self.config.max_pages]
        if len(pages) > len(selected):
            outcome.warnings.append(
                f"OCR limitado a {len(selected)} de {len(pages)} páginas ({OCR_MAX_PAGES_ENV})"
            )
        started = time.perf_counter()
        for number in selected:
            page = document[number - 1]
            try:
                textpage = page.get_textpage_ocr(
                    language=language, dpi=self.config.dpi, full=True, tessdata=str(self.tessdata)
                )
                outcome.texts[number] = page.get_text("text", textpage=textpage)
            except Exception as exc:  # página dañada o fallo de Tesseract: no rompe la carga
                outcome.warnings.append(f"OCR falló en la página {number}: {exc}")
        outcome.seconds = time.perf_counter() - started
        return outcome


_version_cache: dict[str, str] = {}


def tesseract_version(tessdata: Path) -> str:
    key = str(tessdata)
    if key not in _version_cache:
        executable = shutil.which("tesseract") or str(tessdata.parent / "tesseract.exe")
        try:
            output = subprocess.run(
                [executable, "--version"], capture_output=True, text=True, timeout=10, check=False
            )
            first = (output.stdout or output.stderr).splitlines()[0]
            _version_cache[key] = first.replace("tesseract", "").strip() or "desconocida"
        except (OSError, IndexError, subprocess.SubprocessError):
            _version_cache[key] = "desconocida"
    return _version_cache[key]


_lock = threading.Lock()
_cached: tuple[tuple[Any, ...], TesseractOcr | None] | None = None


def get_ocr() -> TesseractOcr | None:
    """Reconocedor configurado, o ``None`` si el OCR está desactivado o no hay Tesseract."""
    global _cached
    config = OcrConfig.from_env()
    key = (config, os.environ.get(TESSDATA_ENV), os.environ.get("TESSDATA_PREFIX"))
    with _lock:
        if _cached is not None and _cached[0] == key:
            return _cached[1]
        tessdata = find_tessdata() if config.enabled else None
        ocr = TesseractOcr(tessdata, config) if tessdata is not None else None
        _cached = (key, ocr)
        return ocr
