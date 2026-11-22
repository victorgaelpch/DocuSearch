# Instalación y demostración en Windows (sin GPU) — DOC-34

Guía para dejar DocuSearch funcionando en una computadora personal con
Windows 10/11, sin GPU y sin servicios en la nube. Todo se ejecuta en
`127.0.0.1`.

## Requisitos

| Componente | Necesario | Para qué |
| --- | --- | --- |
| Python 3.10, 3.11 o 3.12 (64 bits) | Sí | Servidor y procesamiento. Marque "Add python.exe to PATH" al instalarlo |
| Conexión a Internet | Solo durante la instalación | Descargar paquetes y el modelo de spaCy; después funciona sin conexión |
| Tesseract OCR con español | Opcional | PDF escaneados. Sin él quedan como "pendiente de OCR" |
| Extra `semantic` (~1 GB) | Opcional | Búsqueda semántica e híbrida. BM25 y TF-IDF funcionan sin él |

## Instalación paso a paso

Abra PowerShell en la carpeta del proyecto. `-ExecutionPolicy Bypass` se
aplica **solo a ese proceso**; no cambia la configuración de Windows.

```powershell
# 1. Instalar (crea .venv, instala el proyecto y el modelo de spaCy, crea .env)
powershell -ExecutionPolicy Bypass -File scripts\windows\instalar.ps1
#    con búsqueda semántica (PyTorch CPU):  ... instalar.ps1 -Semantico
#    con herramientas de pruebas:           ... instalar.ps1 -Desarrollo

# 2. Crear la contraseña del Administrador (no se muestra; se guarda solo su hash en .env)
powershell -ExecutionPolicy Bypass -File scripts\windows\configurar-cuenta.ps1
#    cuenta de solo consulta (opcional):    ... configurar-cuenta.ps1 -Rol user

# 3. Cargar los documentos de demostración (sintéticos, sin datos personales)
.\.venv\Scripts\python.exe -m backend.app.cli demo

# 4. Iniciar y abrir el navegador en http://127.0.0.1:8000/
powershell -ExecutionPolicy Bypass -File scripts\windows\iniciar.ps1
```

`scripts\windows\verificar.ps1` (o `python -m backend.app.cli doctor`) revisa
Python, paquetes, modelo de spaCy, cuenta, carpeta de datos, OCR, semántica y
puerto, y dice qué falta y cómo resolverlo.

### Sin scripts (manual)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1          # si lo bloquea la política: use los scripts o
                                       # Set-ExecutionPolicy -Scope Process Bypass
python -m pip install -e ".[model]"
copy .env.example .env
python -m backend.app.cli hash-password --env-file .env
python -m backend.app.cli demo
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

## Modos de funcionamiento

| Modo | Instalación | Qué funciona | Degradación |
| --- | --- | --- | --- |
| Base (sin conexión) | `instalar.ps1` | Carga PDF/DOCX/TXT, visor, BM25, TF-IDF, edición, panel de índices | Semántica e híbrida responden "no disponible" (503) con instrucciones; los botones semánticos del panel aparecen desactivados |
| + OCR | Tesseract con español | Los PDF escaneados se reconocen al cargarlos o con "Reconocer PDF escaneados" | Sin Tesseract: el documento queda "pendiente de OCR", se puede ver y descargar y no aparece en las búsquedas |
| + Semántica | `instalar.ps1 -Semantico` | Semántica e híbrida (la recomendada según MIRACL-es) | La primera búsqueda descarga el modelo (~460 MB) y tarda; después funciona sin conexión |

### Instalar Tesseract (opcional)

1. Descargue el instalador de Windows de Tesseract (UB Mannheim) e instálelo en
   la ruta predeterminada.
2. Si el idioma español no se incluyó: `python -m backend.app.cli tessdata`
   (descarga `spa` y `eng` a `data\tessdata`).
3. `python -m backend.app.cli doctor` debe mostrar `[OK ] OCR (Tesseract + español)`.

## Guion de comandos para la demostración

| Acción | Dónde |
| --- | --- |
| Iniciar sesión | http://127.0.0.1:8000/#/login |
| Cargar documentos (o arrastrarlos) | Documentos → "Cargar documentos" |
| Buscar | Buscar → `acuíferos subterráneos` (BM25) → abrir el resultado |
| Ver el fragmento y la página de origen | El título del resultado abre el visor con el fragmento resaltado; "Vista del PDF" abre la página |
| Comparar métodos | Buscar → Método "Híbrida" + "Comparar con BM25" (requiere el extra semántico) |
| Editar o eliminar | En el visor: "Editar datos" / "Eliminar" |
| Reindexar | Índices → "Reindexar" (o `python -m backend.app.cli reindex`) |
| Consultas de ejemplo | `python -m backend.app.cli demo --queries` (`demo/consultas.json`) |

## Problemas frecuentes

| Síntoma | Causa y solución |
| --- | --- |
| "no se puede cargar ... porque la ejecución de scripts está deshabilitada" | Ejecute los scripts con `powershell -ExecutionPolicy Bypass -File ...` (solo ese proceso) |
| `py` o `python` no se reconoce | Python no está en el PATH: reinstálelo marcando "Add python.exe to PATH" |
| `[ERR] Modelo spaCy es_core_news_sm` | Sin red durante la instalación: vuelva a ejecutar `instalar.ps1` con conexión |
| `[ERR] Cuenta de Administrador` | Ejecute `configurar-cuenta.ps1`; el hash se guarda en `.env` |
| Error al arrancar: "hash no válido" | El hash en `.env` está incompleto; vuelva a ejecutar `configurar-cuenta.ps1` |
| "Búsqueda semántica no disponible" | Instale `-Semantico`; la primera búsqueda necesita red para descargar el modelo. Sin red, use BM25 |
| La primera búsqueda semántica tarda mucho | Está cargando el modelo en CPU; las siguientes tardan milisegundos sobre el índice caliente |
| PDF "pendiente de OCR" | Instale Tesseract con español y use "Reconocer PDF escaneados" en Índices |
| "Puerto 8000 ocupado" | Ya hay un servidor en marcha, o use `iniciar.ps1 -Puerto 8010` |
| "Acceso denegado" en `data\` | Mueva el proyecto fuera de carpetas protegidas (p. ej. `C:\Program Files`) o defina `DOCUSEARCH_DATA_DIR` en `.env` |
| `/docs` (Swagger) en blanco sin Internet | Swagger carga sus archivos de un CDN; la aplicación web y la API funcionan igual |
| RAG / Ollama | Aún no forma parte de la entrega v1.0 (Issues DOC-38 y DOC-39, opcionales) |

## Plataformas verificadas

| Plataforma | Cómo | Resultado |
| --- | --- | --- |
| Ubuntu (GitHub Actions), Python 3.10, 3.11 y 3.12 | Suite completa en cada PR | Ver checks `tests (3.x)` |
| Ubuntu + Chromium (GitHub Actions) | `web-e2e`: navegador real | Ver check `web-e2e` |
| **Windows Server (GitHub Actions `windows-latest`), Python 3.11, Windows PowerShell 5.1** | `windows-install`: instalación limpia con `instalar.ps1`, cuenta, demostración, servidor y recorrido HTTP (web, JS con tipo correcto, login, documentos, búsqueda BM25) | Ver check `windows-install` |
| Windows 10/11 de escritorio | **No verificado en esta entrega**: no se instaló nada en equipos personales. Se recomienda ejecutar `verificar.ps1` y el guion anterior antes de presentar |
| OCR en Windows | **No verificado** (el job de Windows no instala Tesseract; se prueba la degradación) |
| Búsqueda semántica en Windows | **No verificada** en Windows (sí en Linux con el modelo real, check `semantic-model`) |
