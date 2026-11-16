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

## Instalación opcional del lector documental

Cuando se implemente DOC-03, se podrán instalar dependencias con:

```bash
python -m pip install -e ".[dev,documents]"
```

La opción `documents` solo instala las bibliotecas; **la extracción aún no está implementada**.

## Flujo Git

Crear una rama por Issue y asociar el Pull Request al Issue correspondiente. El PR de esta entrega usa `Closes #1` para cerrar el Issue al fusionarse con `main`.
