"""Proveedores de generación para RAG (DOC-38). Solo locales.

Por diseño solo se admite un servidor en esta misma computadora (Ollama en
``127.0.0.1``): los fragmentos de documentos privados nunca se envían a un
servicio remoto. Sin proveedor configurado, el RAG queda desactivado y la
búsqueda normal sigue funcionando.
"""

from __future__ import annotations

import ipaddress
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

PROVIDER_ENV = "DOCUSEARCH_RAG_PROVIDER"
MODEL_ENV = "DOCUSEARCH_RAG_MODEL"
URL_ENV = "DOCUSEARCH_RAG_URL"
TIMEOUT_ENV = "DOCUSEARCH_RAG_TIMEOUT"
DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.2:3b"
DEFAULT_TIMEOUT = 120.0
MAX_ANSWER_TOKENS = 512


class RagUnavailableError(RuntimeError):
    """No hay proveedor configurado o no responde."""


class RagProviderError(RuntimeError):
    """El proveedor respondió con un error."""


class Generator(Protocol):
    name: str
    model: str

    def generate(self, system: str, user: str) -> str: ...

    def status(self) -> dict[str, Any]: ...


def validate_local_url(url: str) -> str:
    """Acepta solo http(s) hacia esta computadora (loopback)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"{URL_ENV} debe ser una URL http(s)")
    host = parts.hostname
    if host != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError
        except ValueError as exc:
            raise ValueError(
                f"{URL_ENV} debe apuntar a esta computadora (127.0.0.1 o localhost): "
                "DocuSearch no envía documentos a servicios remotos"
            ) from exc
    if parts.username or parts.password:
        raise ValueError(f"{URL_ENV} no debe contener credenciales")
    return url.rstrip("/")


@dataclass
class RagConfig:
    provider: str = ""
    model: str = DEFAULT_MODEL
    url: str = DEFAULT_URL
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls) -> "RagConfig":
        provider = (os.environ.get(PROVIDER_ENV) or "").strip().lower()
        if provider not in ("", "off", "ollama"):
            raise ValueError(f"{PROVIDER_ENV} admite 'ollama' u 'off'")
        timeout_raw = (os.environ.get(TIMEOUT_ENV) or "").strip()
        return cls(
            provider="" if provider == "off" else provider,
            model=(os.environ.get(MODEL_ENV) or DEFAULT_MODEL).strip(),
            url=validate_local_url((os.environ.get(URL_ENV) or DEFAULT_URL).strip()),
            timeout=float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT,
        )

    @property
    def enabled(self) -> bool:
        return self.provider == "ollama"


class OllamaGenerator:
    """Cliente mínimo de la API de Ollama (``/api/chat``), sin herramientas."""

    name = "ollama"

    def __init__(self, config: RagConfig) -> None:
        self.config = config
        self.model = config.model
        self.url = validate_local_url(config.url)

    def _request(self, path: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url}{path}", data=data, method="POST" if data else "GET",
            headers={"Content-Type": "application/json"},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # nunca a través de un proxy
        try:
            with opener.open(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise RagProviderError(f"Ollama respondió {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RagUnavailableError(f"no se pudo contactar con Ollama en {self.url}: {exc}") from exc

    def generate(self, system: str, user: str) -> str:
        body = self._request(
            "/api/chat",
            {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "stream": False,
                "options": {"temperature": 0, "num_predict": MAX_ANSWER_TOKENS},
            },
            self.config.timeout,
        )
        message = body.get("message") or {}
        return str(message.get("content") or "")

    def status(self) -> dict[str, Any]:
        try:
            tags = self._request("/api/tags", None, 3.0)
        except (RagUnavailableError, RagProviderError) as exc:
            return {"reachable": False, "model_available": False, "detail": str(exc)}
        names = {model.get("name") for model in tags.get("models", [])}
        return {"reachable": True, "model_available": self.model in names, "models": sorted(n for n in names if n)}


def build_generator(config: RagConfig) -> Generator | None:
    return OllamaGenerator(config) if config.enabled else None
