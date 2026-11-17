# Fragmentación de documentos (DOC-07)

Código: `backend/app/nlp/chunking.py`; integración en
`backend/app/documents/service.py`.

## Configuración

| Parámetro | Por defecto | Variable de entorno |
| --- | --- | --- |
| Tamaño del fragmento (palabras) | **200** | `DOCUSEARCH_CHUNK_SIZE` |
| Solapamiento (palabras) | **30** | `DOCUSEARCH_CHUNK_OVERLAP` |

Paso entre ventanas = 200 − 30 = 170 palabras. Se exige `0 <= overlap < size`.
La configuración usada se guarda en `Document.extra["chunking"]`
(`{"version": 1, "chunk_size": 200, "overlap": 30}`).

## Algoritmo

1. Las palabras son secuencias sin espacios (`\S+`) del **texto extraído
   original** (DOC-03), sin limpiar. Así, `char_start`/`char_end` apuntan
   exactamente a ese texto y el fragmento se reconstruye con
   `text[char_start:char_end]`.
2. Ventanas `[0, 200)`, `[170, 370)`, `[340, 540)`… hasta cubrir la última
   palabra. Si una ventana ya llega al final, no se crea otra (sin colas
   redundantes).
3. Página: `page_start` = página de la primera palabra y `page_end` = página de
   la última (`ExtractionResult.page_for_offset`). Un fragmento puede abarcar
   dos páginas de un PDF. DOCX y TXT no tienen página (`None`).
4. `chunk_id = <doc_id>_c<orden de 5 dígitos>`.

Es **determinista**: no hay azar, así que el mismo texto con la misma
configuración produce los mismos fragmentos e IDs. Un texto menor que 200
palabras da un único fragmento; un texto vacío no da ninguno.

La limpieza léxica o semántica (DOC-06) se aplica **al indexar**, no al
fragmentar, para no perder la correspondencia con el texto original.

## Integración

- `POST /documents` fragmenta y guarda los fragmentos junto con el documento,
  en una operación todo-o-nada: si falla el guardado de fragmentos, se borran
  el documento y el original. La respuesta incluye `chunk_count`.
- `GET /documents/{doc_id}/chunks` devuelve los fragmentos con offsets y
  páginas, y la configuración usada.
- `python -m backend.app.cli rechunk [--collection user]` vuelve a extraer y
  fragmentar todos los documentos desde sus originales (p. ej. tras cambiar
  `DOCUSEARCH_CHUNK_SIZE`). Los documentos cuyo original falta o no se puede
  leer se informan sin perder sus fragmentos anteriores.

## Limitaciones

- La ventana cuenta palabras, no oraciones: un fragmento puede empezar o
  terminar a mitad de frase (el solapamiento de 30 palabras lo mitiga).
- Los PDF con `needs_ocr` no tienen texto y quedan sin fragmentos.
- Máximo 100 000 fragmentos por documento (límite del formato de `chunk_id`).
