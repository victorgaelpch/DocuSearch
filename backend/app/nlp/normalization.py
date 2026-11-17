"""Normalización común de texto (DOC-06).

``clean_text`` se aplica tanto al pipeline léxico como al semántico y nunca
elimina palabras: solo corrige artefactos de extracción y marcado.

* Unicode NFC y sustitución de ligaduras tipográficas (ﬁ → fi).
* Eliminación de guiones suaves, caracteres de ancho cero, BOM y de control.
* Eliminación de etiquetas HTML/XML y decodificación de entidades (&amp;).
* Unión de palabras cortadas con guion al final de línea (frecuente en PDF).
* Colapso de espacios y de líneas en blanco repetidas.
"""

from __future__ import annotations

import html
import re
import unicodedata

_LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
}
_INVISIBLE = dict.fromkeys(map(ord, "­​‌‍⁠﻿"), None)
_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9:-]*(?:\s[^<>]{0,500})?/?>")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HYPHEN_BREAK = re.compile(r"(\w)[-‐‑]\n[ \t]*(\w)")
_SPACES = re.compile(r"[ \t\f\v  -   　]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")
_SPACE_AROUND_NEWLINE = re.compile(r" *\n *")


def _remove_control_chars(text: str) -> str:
    return "".join(
        ch if ch == "\n" or unicodedata.category(ch)[0] != "C" else " " for ch in text
    )


def clean_text(text: str | None) -> str:
    """Limpia artefactos sin alterar el contenido lingüístico."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.translate(_INVISIBLE)
    for ligature, replacement in _LIGATURES.items():
        text = text.replace(ligature, replacement)
    text = unicodedata.normalize("NFC", text)
    text = _HTML_COMMENT.sub(" ", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _remove_control_chars(text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _SPACES.sub(" ", text)
    text = _SPACE_AROUND_NEWLINE.sub("\n", text)
    text = _MANY_NEWLINES.sub("\n\n", text)
    return text.strip()


def is_blank(text: str | None) -> bool:
    """``True`` si no queda texto útil tras la limpieza."""
    return not clean_text(text)


_COMBINING_ACUTE_ETC = {"́", "̀", "̂", "̈"}


def strip_accents(text: str) -> str:
    """Quita tildes y diéresis de las vocales, pero conserva la ``ñ``.

    ``búsqueda`` → ``busqueda``, ``pingüino`` → ``pinguino``, ``año`` → ``año``.
    """
    decomposed = unicodedata.normalize("NFD", text)
    kept = []
    for index, ch in enumerate(decomposed):
        if ch in _COMBINING_ACUTE_ETC:
            continue
        if ch == "̃" and index and decomposed[index - 1] not in "nN":
            continue  # virgulilla sobre otras letras (ã, õ)
        kept.append(ch)
    return unicodedata.normalize("NFC", "".join(kept))
