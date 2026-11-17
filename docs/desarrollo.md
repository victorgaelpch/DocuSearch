# Guía de desarrollo

## Preparación

En Windows PowerShell, desde la raíz del repositorio:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q
python -m uvicorn backend.app.main:app --reload
```

En Linux o macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
python -m uvicorn backend.app.main:app --reload
```

## Lectores de documentos

Desde DOC-03, PyMuPDF y python-docx son dependencias principales y se instalan
con `pip install -e ".[dev]"`. El extra `documents` conserva `python-multipart`,
necesario para la carga de archivos de DOC-04.

Para regenerar los archivos de prueba sintéticos:

```bash
python tests/fixtures/generate_fixtures.py
```

## Flujo Git

Crear una rama por Issue y asociar el Pull Request al Issue correspondiente. El PR de esta entrega usa `Closes #1` para cerrar el Issue al fusionarse con `main`.
