"""Instalación local y reproducible de idiomas de Tesseract (DOC-23).

Descarga los modelos ``.traineddata`` del repositorio oficial
``tesseract-ocr/tessdata_{fast,best}`` (licencia Apache-2.0) **fijados a un
commit** y verifica su SHA-256. Se guardan en ``data/tessdata/`` (fuera de
Git), que ``ocr.find_tessdata`` usa antes que la instalación del sistema. No
requiere permisos de administrador.

Variantes medidas (``docs/lectores.md``): ``fast`` (2,3 MB español) da casi
la misma precisión que ``best`` (13,6 MB) en la mitad de tiempo, por eso es la
predeterminada.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

USER_AGENT = "DocuSearch-AI/0.2 (tessdata installer)"
TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class TessdataSource:
    repository: str
    commit: str
    sha256: dict[str, str]

    def url(self, language: str) -> str:
        return f"https://raw.githubusercontent.com/tesseract-ocr/{self.repository}/{self.commit}/{language}.traineddata"


SOURCES: dict[str, TessdataSource] = {
    "fast": TessdataSource(
        "tessdata_fast",
        "87416418657359cb625c412a48b6e1d6d41c29bd",
        {
            "spa": "6f2e04d02774a18f01bed44b1111f2cd7f3ba7ac9dc4373cd3f898a40ea6b464",
            "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
        },
    ),
    "best": TessdataSource(
        "tessdata_best",
        "e12c65a915945e4c28e237a9b52bc4a8f39a0cec",
        {
            "spa": "e2c1ffdad8b30f26c45d4017a9183d3a7f9aa69e59918be4f88b126fac99ab2c",
            "eng": "8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba",
        },
    ),
}


class TessdataError(RuntimeError):
    """Descarga fallida, idioma no admitido o hash distinto del esperado."""


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 (URL fija)
        return response.read()


def install_languages(destination: Path, languages: list[str], variant: str = "fast") -> dict[str, dict[str, object]]:
    """Descarga y verifica ``languages`` en ``destination``; omite los ya correctos."""
    if variant not in SOURCES:
        raise TessdataError(f"variante desconocida: {variant}; use {', '.join(SOURCES)}")
    source = SOURCES[variant]
    unknown = [lang for lang in languages if lang not in source.sha256]
    if unknown:
        raise TessdataError(f"idioma(s) sin hash verificado: {', '.join(unknown)}; admitidos: {', '.join(source.sha256)}")
    destination.mkdir(parents=True, exist_ok=True)
    report: dict[str, dict[str, object]] = {}
    for language in languages:
        target = destination / f"{language}.traineddata"
        expected = source.sha256[language]
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
            report[language] = {"status": "already_installed", "bytes": target.stat().st_size}
            continue
        try:
            data = _download(source.url(language))
        except OSError as exc:
            raise TessdataError(f"no se pudo descargar {language}: {exc}") from exc
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise TessdataError(f"SHA-256 inesperado para {language}: {actual}")
        fd, tmp = tempfile.mkstemp(dir=destination, prefix=f".tmp-{language}-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        report[language] = {"status": "installed", "bytes": len(data), "sha256": actual}
    return {"variant": variant, "commit": source.commit, "destination": str(destination), "languages": report}
