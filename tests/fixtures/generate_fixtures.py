"""Genera los archivos sintéticos de prueba de DOC-03.

Uso (desde la raíz del repositorio):

    python tests/fixtures/generate_fixtures.py

Los textos esperados están en ``expected.json``. Los archivos generados se
versionan para que las pruebas no dependan de descargas ni de datos privados;
este script permite reproducirlos.
"""

from __future__ import annotations

import json
from pathlib import Path

import docx
import pymupdf

HERE = Path(__file__).resolve().parent
EXPECTED = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))


def build_pdf(path: Path) -> None:
    spec = EXPECTED["muestra.pdf"]
    document = pymupdf.open()
    for page_text in spec["pages"]:
        page = document.new_page(width=595, height=842)  # A4
        y = 72
        for line in page_text.split("\n"):
            page.insert_text((72, y), line, fontsize=12, fontname="helv")
            y += 18
    document.set_metadata({"title": spec["title"], "author": "DocuSearch tests"})
    document.save(path, garbage=4, deflate=True, no_new_id=True)
    document.close()


def build_docx(path: Path) -> None:
    spec = EXPECTED["muestra.docx"]
    document = docx.Document()
    document.core_properties.title = spec["title"]
    document.core_properties.author = "DocuSearch tests"
    for block in spec["blocks"]:
        if isinstance(block, list):
            table = document.add_table(rows=len(block), cols=len(block[0]))
            for r, row in enumerate(block):
                for c, value in enumerate(row):
                    table.cell(r, c).text = value
        else:
            document.add_paragraph(block)
    document.save(path)


def build_txt(path: Path) -> None:
    path.write_bytes(EXPECTED["muestra.txt"]["text"].encode("utf-8"))


def main() -> None:
    build_pdf(HERE / "muestra.pdf")
    build_docx(HERE / "muestra.docx")
    build_txt(HERE / "muestra.txt")
    print("fixtures generados en", HERE)


if __name__ == "__main__":
    main()
