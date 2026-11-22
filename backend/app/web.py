"""Interfaz web servida en el mismo origen que la API (DOC-26).

* ``GET /``: ``frontend/index.html`` (aplicación de una página, rutas por hash).
* ``/assets/*``: CSS, JavaScript (módulos ES) e iconos, sin CDN ni Node.

Se fijan los tipos MIME porque en Windows ``mimetypes`` lee el registro y
puede asignar ``text/plain`` a ``.js``, lo que impide cargar módulos ES.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

for _type, _ext in (("text/javascript", ".js"), ("text/css", ".css"), ("image/svg+xml", ".svg")):
    mimetypes.add_type(_type, _ext)


def mount_frontend(application: FastAPI, frontend_dir: Path = FRONTEND_DIR) -> bool:
    """Monta la interfaz si existe ``frontend/index.html``; devuelve si se montó."""
    index = frontend_dir / "index.html"
    if not index.is_file():
        return False

    @application.get("/", include_in_schema=False)
    def web_index() -> FileResponse:
        return FileResponse(index, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})

    application.mount("/assets", StaticFiles(directory=frontend_dir / "assets"), name="assets")
    return True
