# Guion de demostración (8–12 minutos)

Se usan los documentos sintéticos de `demo/` y la cuenta de Administrador
configurada antes de la presentación. Todos los resultados que se muestran
son reales y salen de la ejecución en vivo.

## Antes de empezar (lista de comprobación)

- [ ] `scripts\windows\verificar.ps1` sin `[ERR]`.
- [ ] Datos vacíos o solo con la demo (`DOCUSEARCH_DATA_DIR` aparte si se quiere conservar otra colección).
- [ ] `python -m backend.app.cli demo` ejecutado y servidor iniciado con `iniciar.ps1`.
- [ ] Si se va a mostrar la búsqueda híbrida: extra `semantic` instalado y una búsqueda semántica hecha antes (la primera carga el modelo).
- [ ] Contraseña a mano (no escrita en pantalla).
- [ ] Navegador a pantalla completa en http://127.0.0.1:8000/.

## Desarrollo

| Min. | Qué mostrar | Qué decir |
| --- | --- | --- |
| 0:00–1:00 | Inicio sin sesión; **Buscar** con la colección pública | Problema y objetivo; todo local, sin GPU |
| 1:00–2:00 | **Iniciar sesión** con un error de contraseña y luego la correcta | Cuentas locales, sin contraseña por defecto, sesión HttpOnly y CSRF |
| 2:00–3:30 | **Documentos**: cargar un PDF, un DOCX y un TXT propios (sintéticos); mostrar el resultado por archivo; intentar cargar uno repetido | Extracción, fragmentación 200/30, duplicados por huella SHA-256 |
| 3:30–5:00 | **Buscar** `acuíferos subterráneos` (BM25): posición, puntuación, archivo y página; abrir el resultado | RF01–RF05: título, fragmento, puntuación y origen |
| 5:00–6:00 | **Visor**: fragmento resaltado, página, "Vista del PDF" | RF06: vista completa y trazabilidad al origen |
| 6:00–7:30 | **Buscar** `qué hago con las baterías usadas` en Semántica o Híbrida con "Comparar con BM25" | RF08: BM25 no encuentra la paráfrasis; la semántica sí. Explicar por qué no se comparan las puntuaciones |
| 7:30–8:30 | Resultados de MIRACL (informe, sección 4) | nDCG@10 híbrida 0,752 frente a BM25 0,709 (p < 0,0001), sobre el subconjunto juzgado |
| 8:30–9:30 | **Editar** el título y **Eliminar** un documento; volver a buscar | Coherencia: el documento borrado desaparece de todos los métodos y de los índices en disco |
| 9:30–10:30 | **Índices**: Reindexar; estado y versión final | RF07: tareas con estado real, una a la vez, respaldo por CLI |
| 10:30–12:00 | Checks de GitHub (`tests`, `web-e2e`, `windows-install`, `semantic-model`) y limitaciones | Reproducibilidad (RNF07) y lo que queda fuera: OAuth, RAG, uso multiusuario |

**Plan B sin el extra semántico:** omitir el minuto 6:00–7:30. Mostrar el
aviso "no está disponible" (degradación explícita) y la tabla de MIRACL.

## Capturas

Las de [`capturas/`](capturas/) se generaron con
`tests/e2e/test_web_capturas.py` sobre la demostración sintética (solo BM25).
Para regenerarlas:

```powershell
$env:DOCUSEARCH_TEST_BROWSER = "1"; $env:DOCUSEARCH_E2E_ARTIFACTS = "docs/capturas"
python -m pytest -q tests/e2e/test_web_capturas.py
```

Para capturar en vivo la búsqueda híbrida o semántica, hágalo durante la
demostración con el modelo real instalado. **No use capturas de las pruebas
E2E de la híbrida**: emplean un codificador de prueba y no el modelo real.
