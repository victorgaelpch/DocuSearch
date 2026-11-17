# Corpus experimental de Wikipedia en español (DOC-05)

Código: `backend/app/corpus/wikipedia.py`. Configuración y manifiesto
versionados: `corpus/wikipedia_es/topics.json` y
`corpus/wikipedia_es/manifest.json`. Los textos **no** se versionan; se
guardan en `data/corpus/wikipedia_es/`.

## Procedencia y versión

| Dato | Valor |
| --- | --- |
| Fuente | https://es.wikipedia.org (API de MediaWiki, `action=query`) |
| Licencia del contenido | CC BY-SA 4.0 (cada artículo guarda la URL de su revisión, `?oldid=`) |
| Versión | **Revisiones fijadas por `revid`** en el manifiesto (no un volcado completo) |
| Congelado | `2026-11-17T02:33:02+00:00` (`frozen_at`) |
| Fecha de las revisiones | de 2019-07-30 a 2026-11-16 (última edición de cada artículo al congelar) |
| Conversión | `mwparserfromhell` 0.7.2 + conversor v1 + `clean_text` (DOC-06) |

Se usaron revisiones fijadas en lugar de un volcado (*dump*) porque el volcado
de es.wikipedia ocupa varios GB. Con el `revid` se descarga exactamente el
mismo contenido, y el SHA-256 del texto convertido lo verifica.

## Contenido (medido en la ejecución real)

**275 artículos**, 320 582 palabras. Media de 1165,8 palabras por artículo,
mediana de 735, mínimo 54 y máximo 9286. Al importarlos con la configuración
200/30 se obtuvieron **1978 fragmentos**.

| Tema | Categoría de Wikipedia | Artículos | Media de palabras | Mediana | Mín. | Máx. |
| --- | --- | --- | --- | --- | --- | --- |
| astronomía | Constelaciones | 40 | 1530 | 1329 | 526 | 5044 |
| biología | Orgánulos celulares | 40 | 606 | 379 | 54 | 2264 |
| economía | Indicadores económicos | 40 | 712 | 450 | 62 | 3266 |
| informática | Lenguajes de programación | 40 | 827 | 505 | 81 | 6659 |
| medicina | Enfermedades infecciosas | 40 | 1288 | 606 | 79 | 7506 |
| música | Instrumentos de cuerda | 35 | 791 | 460 | 83 | 4665 |
| química | Elementos químicos | 40 | 2361 | 1851 | 228 | 9286 |

**Excluidos:** 8 artículos con menos de 50 palabras (6 de informática y 2 de
música). No hubo vacíos, redirecciones ni duplicados en esta ejecución, aunque
los filtros existen y tienen pruebas.

## Filtros

- Redirecciones y textos vacíos tras la conversión.
- Menos de **50 palabras** (`--min-words`).
- Duplicados por `pageid` (un artículo en dos categorías) y por texto
  normalizado (minúsculas y espacios).

Cada exclusión queda en `manifest.json → excluded` con su motivo.

## Conversión del wikitexto

Se eliminan:
- plantillas (fichas, navegación);
- etiquetas `<ref>`, `<math>` y `<gallery>`, y las tablas;
- enlaces a archivos, imágenes y categorías;
- las secciones finales sin contenido (Referencias, Notas, Bibliografía, Enlaces externos, Véase también).

Los títulos de sección se conservan como texto.

## Comandos

```powershell
# 1. Elegir artículos y fijar revisiones (consulta la versión actual; cambia el manifiesto)
python -m backend.app.cli corpus freeze
# 2. Reconstruir los textos exactos del manifiesto (verifica SHA-256)
python -m backend.app.cli corpus build
# 3. Cargar en la colección wikipedia_es (idempotente)
python -m backend.app.cli corpus import
# Estadísticas del manifiesto
python -m backend.app.cli corpus stats
```

Para **reproducir** el corpus basta con `build` + `import`. `freeze` solo se
usa para crear una versión nueva del corpus, y ese cambio debe revisarse en un
PR.

El cliente hace una petición por segundo y reintenta los errores 429 y 5xx
respetando `Retry-After`. La política de Wikimedia pide un `User-Agent` con
datos de contacto: define `DOCUSEARCH_WIKI_USER_AGENT` con el del equipo. Por
defecto se usa uno genérico.

## Separación de los documentos del usuario

- Colección `wikipedia_es` y `source_type = corpus`. El `doc_id` depende de la
  colección, así que el mismo texto subido por un usuario tiene otro ID.
- Originales en `originals/wikipedia_es/`, y `GET /documents` lista solo la
  colección `user`.
- `extra` guarda `topic`, `pageid`, `revid` y `license`, y `source_uri` la URL
  de la revisión.

## Limitaciones

- **Muestreo no aleatorio:** se toman los primeros artículos de cada
  categoría por orden alfabético (`cmsort=sortkey`). Por ejemplo, en
  informática predominan los lenguajes que empiezan por A. Sirve para un
  experimento reproducible, pero no es una muestra representativa de
  Wikipedia.
- Solo se usan siete temas, de una categoría cada uno, y los temas están
  desbalanceados en longitud: química es unas cuatro veces más larga que
  biología.
- Las consultas anotadas para evaluación se definen en DOC-09.
