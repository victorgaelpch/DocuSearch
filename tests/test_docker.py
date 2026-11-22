"""Configuración de Docker Compose local (DOC-41). La ejecución real se prueba en CI (docker-local)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
yaml = pytest.importorskip("yaml")


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))


def test_port_is_published_only_on_localhost(compose) -> None:
    ports = compose["services"]["docusearch"]["ports"]
    assert ports and all(str(p).startswith("127.0.0.1:") for p in ports)
    assert "0.0.0.0" not in (ROOT / "compose.yaml").read_text(encoding="utf-8").split("#")[0]


def test_data_lives_in_a_named_volume(compose) -> None:
    service = compose["services"]["docusearch"]
    assert "docusearch-data:/data" in service["volumes"] and "docusearch-data" in compose["volumes"]
    assert service["restart"] == "unless-stopped"


def test_container_is_hardened_and_has_no_secrets(compose) -> None:
    service = compose["services"]["docusearch"]
    assert service["read_only"] is True and service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert "environment" not in service  # los secretos van en .env, fuera del repositorio
    assert service["env_file"][0]["path"] == ".env" and service["env_file"][0]["required"] is False


def test_dockerfile_runs_as_non_root_with_healthcheck() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^USER docusearch$", text, re.MULTILINE)
    assert "HEALTHCHECK" in text and "/health/ready" in text
    assert 'VOLUME ["/data"]' in text and "DOCUSEARCH_DATA_DIR=/data" in text
    assert not re.search(r"^COPY .*\b(data|\.env)\b", text, re.MULTILINE)
    assert "--workers\", \"1\"" in text  # sesiones y tareas en memoria: un solo proceso


def test_dockerignore_excludes_private_data() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for entry in ("data", ".env", ".git", "e2e-artifacts"):
        assert entry in ignored
