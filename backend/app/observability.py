"""Registros estructurados, identificador de petición y métricas locales (DOC-40).

* Una línea JSON por petición en el registro ``docusearch``: identificador,
  método, ruta **sin la cadena de consulta** (puede contener lo que se buscó),
  código, duración y rol. Nunca se registran cuerpos, texto de documentos,
  consultas, cookies ni contraseñas.
* ``X-Request-ID`` en todas las respuestas; un error no controlado responde
  500 con ese identificador para buscarlo en el registro.
* Métricas en memoria (se reinician con el servidor): latencias de búsqueda
  por método, separando la primera consulta tras construir un índice (en frío)
  de las siguientes (en caliente), y memoria del proceso. No es un sistema de
  monitoreo de producción.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
import traceback
import uuid
from collections import deque
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

LOGGER_NAME = "docusearch"
LOG_LEVEL_ENV = "DOCUSEARCH_LOG_LEVEL"
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
SAMPLES = 1000
WARN_MS = 2000.0  # RNF01: búsqueda sobre índice caliente en menos de 2 s

logger = logging.getLogger(LOGGER_NAME)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "event": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}) or {})
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    """Configura el registro ``docusearch`` en JSON a stderr (idempotente)."""
    if any(getattr(h, "_docusearch", False) for h in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler._docusearch = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel((os.environ.get(LOG_LEVEL_ENV) or "INFO").upper())
    logger.propagate = False


def log(level: int, event: str, **fields: Any) -> None:
    logger.log(level, event, extra={"fields": fields})


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return round(ordered[position], 2)


def process_memory_mb() -> float | None:
    """Memoria residente del proceso en MB, sin dependencias (Linux, macOS y Windows)."""
    try:
        import psutil  # opcional

        return round(psutil.Process().memory_info().rss / 1024 / 1024, 1)
    except Exception:  # noqa: BLE001 — psutil es opcional
        pass
    try:
        with open("/proc/self/status", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            process = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
                return round(counters.WorkingSetSize / 1024 / 1024, 1)
        except Exception:  # noqa: BLE001
            return None
    return None


class Metrics:
    """Latencias de búsqueda por método: en frío (primera tras construir) y en caliente."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._warm: dict[str, deque[float]] = {}
        self._cold: dict[str, list[dict[str, Any]]] = {}
        self._seen: set[tuple[str, str, str]] = set()
        self.started_at = time.time()

    def record_search(self, method: str, collection: str, index_version: str, took_ms: float) -> bool:
        """Registra una búsqueda; devuelve si fue la primera de esa versión de índice (en frío)."""
        key = (method, collection, index_version)
        with self._lock:
            cold = key not in self._seen
            if cold:
                self._seen.add(key)
                self._cold.setdefault(method, []).append({"collection": collection, "ms": round(took_ms, 2)})
                self._cold[method] = self._cold[method][-20:]
            else:
                self._warm.setdefault(method, deque(maxlen=SAMPLES)).append(took_ms)
            return cold

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            methods = sorted(set(self._warm) | set(self._cold))
            search = {}
            for method in methods:
                warm = list(self._warm.get(method, ()))
                p95 = _percentile(warm, 0.95)
                search[method] = {
                    "warm": {"count": len(warm), "p50_ms": _percentile(warm, 0.5), "p95_ms": p95,
                             "max_ms": round(max(warm), 2) if warm else None},
                    "cold": list(self._cold.get(method, [])),
                    "over_budget": p95 is not None and p95 > WARN_MS,
                }
        return {
            "since": self.started_at,
            "uptime_s": round(time.time() - self.started_at, 1),
            "budget_ms": WARN_MS,
            "search": search,
            "memory_mb": process_memory_mb(),
        }


def _route_path(scope: Scope) -> str:
    route = scope.get("route")
    template = getattr(route, "path", None) or getattr(route, "path_format", None)
    return template or scope.get("path", "")


class RequestLogMiddleware:
    """Identificador de petición, registro por petición y 500 controlado."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex[:16]
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status = {"code": 500, "sent": False}

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                status["sent"] = True
                message = {**message, "headers": [*message.get("headers", []), (b"x-request-id", request_id.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:  # error no controlado: se registra y se responde sin detalles
            log(logging.ERROR, "unhandled_error", request_id=request_id, method=scope.get("method"),
                path=_route_path(scope), error=type(exc).__name__,
                trace=traceback.format_exc(limit=6).splitlines()[-6:])
            if status["sent"]:
                raise
            body = json.dumps({"error": {"code": "internal_error",
                                         "message": f"error interno; consulte el registro del servidor con el identificador {request_id}",
                                         "request_id": request_id}}, ensure_ascii=False).encode()
            await send({"type": "http.response.start", "status": 500, "headers": [
                (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                (b"x-request-id", request_id.encode()), (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": body})
            status["code"] = 500
        finally:
            path = _route_path(scope)
            if not path.startswith("/assets"):
                log(logging.INFO, "request", request_id=request_id, method=scope.get("method"), path=path,
                    status=status["code"], duration_ms=round((time.perf_counter() - started) * 1000, 2))
