"""Documentos sintéticos para pruebas (sin datos personales)."""

from __future__ import annotations

import pymupdf


def scanned_pdf(pages: list[str | None], dpi: int = 150) -> bytes:
    """PDF cuyas páginas son imágenes del texto (``None`` = página en blanco)."""
    output = pymupdf.open()
    for text in pages:
        source = pymupdf.open()
        page = source.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(50, 60, 550, 800), text, fontsize=13)
        pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        target = output.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(target.rect, stream=pixmap.tobytes("png"))
        source.close()
    data = output.tobytes(deflate=True)
    output.close()
    return data
