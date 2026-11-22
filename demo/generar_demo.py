"""Genera los documentos sintéticos de la demostración (DOC-34).

Uso: ``python demo/generar_demo.py`` (los archivos resultantes se versionan
para que la demostración funcione sin conexión). Todos los textos son
originales y ficticios: no contienen datos personales.
"""

from __future__ import annotations

from pathlib import Path

import docx
import pymupdf

HERE = Path(__file__).resolve().parent
OUT = HERE / "documentos"

AGUA = [
    (
        "El ciclo del agua\n\n"
        "El agua de mares, ríos y lagos se evapora con el calor del sol.\n"
        "El vapor asciende, se enfría y se condensa en pequeñas gotas\n"
        "que forman las nubes. Cuando las gotas crecen, caen como lluvia,\n"
        "granizo o nieve: es la precipitación.\n\n"
        "Una parte del agua que cae corre por la superficie hasta los ríos;\n"
        "otra se infiltra en el suelo y alimenta los acuíferos subterráneos."
    ),
    (
        "Importancia para las ciudades\n\n"
        "Los acuíferos abastecen de agua potable a muchas ciudades.\n"
        "Si se extrae más agua de la que se recarga, el nivel del acuífero\n"
        "baja y el terreno puede hundirse lentamente.\n\n"
        "Recomendaciones: captar agua de lluvia, reparar fugas y reutilizar\n"
        "el agua gris para el riego de jardines."
    ),
]

REDES = [
    "Apuntes de la clase: redes neuronales",
    "Una red neuronal artificial está formada por capas de neuronas conectadas. Cada conexión tiene un peso que se ajusta durante el entrenamiento.",
    "El entrenamiento compara la salida de la red con la respuesta correcta y calcula un error. El algoritmo de retropropagación reparte ese error hacia atrás y el descenso de gradiente modifica los pesos para reducirlo.",
    "Si la red memoriza los ejemplos en lugar de aprender patrones generales hay sobreajuste. Se combate con más datos, regularización o deteniendo el entrenamiento a tiempo.",
    [["Concepto", "Idea clave"], ["Época", "Una pasada completa por los datos"], ["Tasa de aprendizaje", "Tamaño de cada ajuste de los pesos"]],
]

RECICLAJE = """Guía rápida de reciclaje en casa

Separe los residuos en tres grupos: orgánicos, reciclables y sanitarios.

Los residuos orgánicos, como cáscaras de fruta y restos de verdura, sirven para hacer composta. En unas semanas se convierten en abono para las plantas.

El papel, el cartón, el vidrio y las latas de aluminio se reciclan si están limpios y secos. Enjuague los envases antes de guardarlos.

Las pilas y los aparatos electrónicos no van a la basura común: llévelos a un centro de acopio, porque contienen metales que contaminan el suelo y el agua.
"""

ESCANEADO = (
    "Aviso escaneado\n\n"
    "La biblioteca de la facultad cerrará por mantenimiento\n"
    "del sistema eléctrico durante el periodo vacacional.\n"
    "Los préstamos vencidos podrán devolverse en la oficina\n"
    "de control escolar."
)


def build_pdf(path: Path) -> None:
    document = pymupdf.open()
    for text in AGUA:
        page = document.new_page(width=595, height=842)
        page.insert_textbox(pymupdf.Rect(72, 72, 523, 770), text, fontsize=12, fontname="helv")
    document.set_metadata({"title": "Informe: el ciclo del agua", "author": "Demostración DocuSearch"})
    document.save(path, garbage=4, deflate=True, no_new_id=True)
    document.close()


def build_docx(path: Path) -> None:
    document = docx.Document()
    document.core_properties.title = "Apuntes: redes neuronales"
    document.core_properties.author = "Demostración DocuSearch"
    for block in REDES:
        if isinstance(block, list):
            table = document.add_table(rows=len(block), cols=len(block[0]))
            for r, row in enumerate(block):
                for c, value in enumerate(row):
                    table.cell(r, c).text = value
        else:
            document.add_paragraph(block)
    document.save(path)


def build_scanned(path: Path) -> None:
    source = pymupdf.open()
    page = source.new_page(width=595, height=842)
    page.insert_textbox(pymupdf.Rect(60, 80, 540, 780), ESCANEADO, fontsize=15, fontname="helv")
    pixmap = page.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
    output = pymupdf.open()
    target = output.new_page(width=595, height=842)
    target.insert_image(target.rect, stream=pixmap.tobytes("png"))
    output.set_metadata({"title": "Aviso escaneado", "author": "Demostración DocuSearch"})
    output.save(path, garbage=4, deflate=True, no_new_id=True)
    output.close()
    source.close()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    build_pdf(OUT / "ciclo-del-agua.pdf")
    build_docx(OUT / "redes-neuronales.docx")
    (OUT / "reciclaje-en-casa.txt").write_bytes(RECICLAJE.encode("utf-8"))
    build_scanned(OUT / "aviso-escaneado.pdf")
    print(f"Documentos de demostración en {OUT}")


if __name__ == "__main__":
    main()
