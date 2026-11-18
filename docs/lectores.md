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
| PDF sin capa de texto, con OCR disponible y texto reconocido | `status = extracted`, `metadata.ocr` (DOC-23) |
| PDF sin capa de texto en ninguna página, sin OCR o sin texto reconocible | `status = needs_ocr` |
| PDF con algunas páginas sin texto | `status = extracted`; esas páginas se reconocen con OCR si está disponible y, si no, se avisa |
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

## OCR de PDF escaneados (DOC-23)

Código: `backend/app/documents/ocr.py`. Pruebas: `tests/test_ocr.py`.

Las páginas de un PDF que no tienen capa de texto se rasterizan a 300 ppp y
se reconocen con **Tesseract** a través de PyMuPDF
(`Page.get_textpage_ocr`). Las páginas con texto digital no se tocan. Cada
página reconocida conserva su número, así que la búsqueda indica la página
correcta.

**Requisito:** Tesseract instalado en el sistema (licencia Apache-2.0). No es
un paquete de Python. Si no se encuentra, el comportamiento es el de v0.1: el
documento queda como `needs_ocr`.

- Windows: instalador de [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki).
  Se detecta en `C:\Program Files\Tesseract-OCR`.
- Linux: `sudo apt-get install tesseract-ocr tesseract-ocr-spa`. El CI lo
  instala así.
- **Idioma español, sin permisos de administrador:**

  ```powershell
  python -m backend.app.cli tessdata                  # spa + eng, variante fast (6,4 MB)
  python -m backend.app.cli tessdata --variant best   # más lenta; 29 MB
  ```

  Descarga los modelos del repositorio oficial `tesseract-ocr/tessdata_fast`
  (o `tessdata_best`), con licencia Apache-2.0. Los modelos están **fijados a
  un commit** y se verifica su SHA-256. Se guardan en `data/tessdata/`, fuera
  de Git; el OCR usa esa carpeta antes que la del sistema. Si ya están, no se
  vuelven a descargar.

| Variable | Por defecto | Uso |
| --- | --- | --- |
| `DOCUSEARCH_OCR` | `auto` | `auto` usa Tesseract si lo encuentra; `off` lo desactiva |
| `DOCUSEARCH_OCR_LANG` | `spa+eng` | Idiomas. Se usan los instalados; si falta alguno, se avisa en `warnings` |
| `DOCUSEARCH_OCR_DPI` | 300 | Resolución del rasterizado |
| `DOCUSEARCH_OCR_MAX_PAGES` | 50 | Máximo de páginas reconocidas por documento, para acotar el tiempo de una carga |
| `DOCUSEARCH_TESSDATA` / `TESSDATA_PREFIX` | detección automática | Carpeta `tessdata` |

**Metadatos:** `metadata.ocr` guarda `engine`, `version`, `dpi`, `language`,
las páginas reconocidas (`pages`) y el tiempo empleado (`seconds`).

**Documentos ya cargados como `needs_ocr`:** los reconoce
`python -m backend.app.cli ocr [--collection user]`. Pasan a `extracted` con
sus fragmentos, y los índices léxicos y semánticos los incorporan en la
siguiente búsqueda.

**Precisión y tiempo medidos** (Windows, Tesseract 5.4.0; 4 páginas de
español con tildes, `ñ` y signos `¿¡`; OCR a 300 ppp; media de las 4 páginas).

Columnas:
- *Palabras exactas*: palabras reconocidas sin ningún error.
- *Palabras sin tildes*: palabras que coinciden tras quitar tildes, como hace
  el buscador léxico.

| Escaneo | Modelo | Similitud de caracteres | Palabras exactas | Palabras sin tildes | s/página |
| --- | --- | --- | --- | --- | --- |
| Limpio (150 ppp, 13 pt) | `eng` del sistema | 0,960 | 73,9 % | 87,7 % | 0,32 |
| Limpio (150 ppp, 13 pt) | **`spa+eng` fast** | **0,999** | **98,1 %** | **98,1 %** | **0,32** |
| Limpio (150 ppp, 13 pt) | `spa+eng` best | 0,998 | 98,9 % | 98,9 % | 0,69 |
| Difícil (100 ppp, 9 pt) | `eng` del sistema | 0,950 | 72,6 % | 85,2 % | 0,26 |
| Difícil (100 ppp, 9 pt) | **`spa+eng` fast** | **0,994** | **96,2 %** | **98,0 %** | **0,28** |
| Difícil (100 ppp, 9 pt) | `spa+eng` best | 0,995 | 97,1 % | 100 % | 0,61 |

- **Solo con el modelo inglés**, el OCR pierde tildes, `ñ` y signos
  (`niho`, `pequeno`, `aprendié`, `¢Quién`). Parte de eso lo compensa el
  buscador, que ignora tildes, pero no la `ñ` (`año` → `ano`).
- **Con el modelo español**, el texto sale casi perfecto. Error real
  observado: a final de línea unió `montaña` con la `y` siguiente
  (`montañay`).
- **Por qué fast es la predeterminada:** precisión casi igual que best, la
  mitad de tiempo y 6,4 MB frente a 29 MB.
- **Limitación de la medición:** el texto es sintético, rasterizado a partir
  de un PDF. Un escaneo real (ruido, inclinación, papel) dará cifras más
  bajas, que no se han medido.

## Limitaciones

- OCR: no reconoce escritura a mano. Con PDF de baja calidad, rotados o en
  columnas, la precisión baja. Un PDF de muchas páginas escaneadas alarga la
  carga (~0,3 s por página) hasta el máximo configurado.
- `.doc` (Word 97-2003), `.odt`, `.rtf` y Google Docs nativos no se admiten
  (Google Docs requiere exportación autorizada, DOC-22).
- DOCX: no se extraen encabezados, pies de página, notas al pie, comentarios ni
  cuadros de texto; tampoco hay números de página (Word los calcula al mostrar).
- PDF: el orden de lectura depende de cómo se generó el archivo (columnas o
  tablas complejas pueden salir desordenadas).
- Límites de tamaño, tipo real del archivo y protección frente a ZIP
  comprimidos de forma abusiva se aplican en la carga (DOC-04).
