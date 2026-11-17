# Lectores de documentos: PDF, DOCX y TXT (DOC-03)

Código: `backend/app/documents/readers.py`.

## Uso

```python
from pathlib import Path
from backend.app.documents import extract_document, build_document

data = Path("informe.pdf").read_bytes()
result = extract_document(data, "informe.pdf")   # ExtractionResult
document = build_document(result)                # Document de DOC-02
```

`extract_document` no escribe en disco ni en la base: la carga, el guardado del
original y la persistencia los orquestará DOC-04.

## Formatos admitidos

| Extensión | Biblioteca | Secciones | Páginas | Metadatos |
| --- | --- | --- | --- | --- |
| `.pdf` | PyMuPDF (`pymupdf`) | una por página | sí (`page_number` desde 1) | título, autor, asunto, creador, productor, páginas sin texto |
| `.docx` | python-docx | un párrafo o una fila de tabla, en el orden del documento | no | título, autor, número de párrafos y filas de tabla |
| `.txt` | biblioteca estándar | el texto completo | no | codificación detectada |

El texto completo (`result.text`) une las secciones con `"\n\n"`. Cada
`TextSection` guarda `char_start`/`char_end` en ese texto, de modo que la
fragmentación (DOC-07) puede saber la página de cualquier offset con
`result.page_for_offset(offset)`. Los saltos de línea se normalizan a `\n`.
No se eliminan stopwords ni se altera el texto (eso corresponde a DOC-06).

El título sale de los metadatos del archivo si existen y, si no, del nombre del
archivo sin extensión.

## Decodificación de TXT

1. BOM UTF-8 o UTF-16 → se usa esa codificación.
2. Bytes nulos sin BOM → se rechaza como binario (`failed`).
3. UTF-8 estricto.
4. Windows-1252 como último recurso, con aviso en `warnings`.

## Estados y errores

| Situación | Resultado |
| --- | --- |
| Extensión no admitida (`.doc`, `.exe`, sin extensión…) | excepción `UnsupportedFormatError` (no se lee el contenido) |
| Archivo de 0 bytes, o sin texto (solo espacios, DOCX vacío) | `status = empty`, `error` con el motivo |
| PDF sin capa de texto en ninguna página | `status = needs_ocr` |
| PDF con algunas páginas sin texto | `status = extracted` + aviso con las páginas que requieren OCR |
| Cabecera inválida, archivo truncado, ZIP sin partes de Word, contenido de otro formato | `status = failed`, `error` con el motivo |
| PDF protegido con contraseña | `status = failed` |

Los errores de contenido se devuelven en el resultado (no como excepción) para
poder registrar el fallo por archivo y continuar con un lote.

## Fixtures de prueba

`tests/fixtures/muestra.pdf`, `muestra.docx` y `muestra.txt` son sintéticos y
se generan con `python tests/fixtures/generate_fixtures.py`; los textos
esperados están en `tests/fixtures/expected.json`. Los archivos dañados se
generan en memoria dentro de las pruebas. `.gitattributes` evita que Git
cambie sus bytes.

## Licencias de dependencias

- **PyMuPDF**: doble licencia, **GNU AGPL-3.0** o comercial de Artifex. Usarla en
  un servicio accesible por red obliga, bajo AGPL, a ofrecer el código fuente del
  servicio. El repositorio es público, pero **aún no declara una licencia**; si el
  proyecto no puede ser AGPL, la alternativa es `pypdf` (BSD) o `pdfminer.six`
  (MIT), cambiando solo `PdfReader`.
- **python-docx**: MIT.

## Limitaciones

- No hay OCR: los PDF escaneados quedan como `needs_ocr` (DOC-23).
- `.doc` (Word 97-2003), `.odt`, `.rtf` y Google Docs nativos no se admiten
  (Google Docs requiere exportación autorizada, DOC-22).
- DOCX: no se extraen encabezados, pies de página, notas al pie, comentarios ni
  cuadros de texto; tampoco hay números de página (Word los calcula al mostrar).
- PDF: el orden de lectura depende de cómo se generó el archivo (columnas o
  tablas complejas pueden salir desordenadas).
- Límites de tamaño, tipo real del archivo y protección frente a ZIP
  comprimidos de forma abusiva se aplican en la carga (DOC-04).
