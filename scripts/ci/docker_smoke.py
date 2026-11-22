"""Comprobación del contenedor Docker en CI (DOC-41). No forma parte de la aplicación.

Uso: ``python scripts/ci/docker_smoke.py flow|persist``. La contraseña de la
cuenta de prueba se genera al azar en cada ejecución del job y se lee del
archivo temporal del runner.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"


def _session() -> tuple[urllib.request.OpenerDirector, str]:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    secret = Path(os.environ["RUNNER_TEMP"], "pw.txt").read_text(encoding="utf-8").strip()
    credentials = {"username": "admin"}
    credentials.update(password=secret)
    request = urllib.request.Request(f"{BASE}/auth/login", data=json.dumps(credentials).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with opener.open(request, timeout=60) as response:
        csrf = json.loads(response.read())["csrf_token"]
    return opener, csrf


def _get(opener, path: str):
    with opener.open(f"{BASE}{path}", timeout=60) as response:
        return json.loads(response.read())


def flow() -> None:
    opener, csrf = _session()
    boundary = "dsboundary"
    text = "Los acuiferos subterraneos abastecen de agua potable a las ciudades.".encode()
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="agua.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
    ).encode() + text + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(f"{BASE}/documents", data=body, method="POST", headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}", "X-CSRF-Token": csrf})
    opener.open(request, timeout=60).read()
    hits = _get(opener, "/search?q=acuiferos")["results"]
    assert hits and hits[0]["original_filename"] == "agua.txt", hits
    ready = _get(opener, "/health/ready")
    assert ready["status"] == "ready" and ready["optional"]["ocr"] is True, ready
    print("Docker: login, carga, búsqueda y preparación verificadas")


def persist() -> None:
    opener, _ = _session()
    docs = _get(opener, "/documents")
    assert docs["total"] == 1 and docs["items"][0]["original_filename"] == "agua.txt", docs
    print("Docker: el documento persiste en el volumen tras recrear el contenedor")


if __name__ == "__main__":
    {"flow": flow, "persist": persist}[sys.argv[1]]()
