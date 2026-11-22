"""Demostración reproducible, diagnóstico y configuración local (DOC-34)."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from backend.app.auth.passwords import verify_password
from backend.app.cli import main as cli_main
from backend.app.config import Settings, load_env_file
from backend.app.documents.ocr import find_tessdata
from tests.auth_helpers import admin_client

DEMO = Path(__file__).resolve().parents[1] / "demo"
QUERIES = json.loads((DEMO / "consultas.json").read_text(encoding="utf-8"))


@pytest.fixture()
def demo_client(tmp_path: Path, monkeypatch, lexical_pipeline):
    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(tmp_path / "data"))
    assert cli_main(["demo"]) == 0
    return admin_client(Settings.from_env(tmp_path / "data"))


def test_demo_loads_all_documents(demo_client) -> None:
    items = demo_client.get("/documents").json()["items"]
    assert sorted(d["original_filename"] for d in items) == sorted(
        ["ciclo-del-agua.pdf", "redes-neuronales.docx", "reciclaje-en-casa.txt", "aviso-escaneado.pdf"]
    )


@pytest.mark.parametrize("case", QUERIES["lexicas"], ids=lambda c: c["consulta"])
def test_demo_lexical_queries_work_offline_with_bm25(demo_client, case) -> None:
    top = demo_client.get("/search", params={"q": case["consulta"]}).json()["results"][0]
    assert top["original_filename"] == case["documento"]


@pytest.mark.skipif(find_tessdata() is None, reason="requiere Tesseract con español")
def test_demo_ocr_query(demo_client) -> None:
    case = QUERIES["ocr"][0]
    top = demo_client.get("/search", params={"q": case["consulta"]}).json()["results"][0]
    assert top["original_filename"] == case["documento"]


def test_demo_is_idempotent(demo_client, capsys) -> None:
    assert cli_main(["demo"]) == 0
    assert capsys.readouterr().out.count("ya cargado") == 4


def test_demo_documents_contain_no_personal_data() -> None:
    text = " ".join((DEMO / "generar_demo.py").read_text(encoding="utf-8").split())
    assert "@" not in text and "CURP" not in text and "RFC" not in text


# -- .env y hash ------------------------------------------------------------------

def test_env_file_loads_only_docusearch_vars_without_overriding(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# comentario\nDOCUSEARCH_MAX_UPLOAD_MB=7\nDOCUSEARCH_ADMIN_USERNAME='jefa'\n"
        "DOCUSEARCH_USER_PASSWORD_HASH=scrypt$16384$8$1$abc$def\nPATH=/malicioso\n"
        "DOCUSEARCH_CHUNK_SIZE=999\nexport DOCUSEARCH_SESSION_IDLE_MINUTES=\"15\"\nLINEA SIN IGUAL\n",
        encoding="utf-8",
    )
    snapshot = dict(os.environ)
    try:
        for key in ("DOCUSEARCH_MAX_UPLOAD_MB", "DOCUSEARCH_ADMIN_USERNAME", "DOCUSEARCH_USER_PASSWORD_HASH", "DOCUSEARCH_SESSION_IDLE_MINUTES"):
            os.environ.pop(key, None)
        os.environ["DOCUSEARCH_CHUNK_SIZE"] = "150"
        loaded = load_env_file(env)
        assert set(loaded) == {"DOCUSEARCH_MAX_UPLOAD_MB", "DOCUSEARCH_ADMIN_USERNAME", "DOCUSEARCH_USER_PASSWORD_HASH", "DOCUSEARCH_SESSION_IDLE_MINUTES"}
        assert os.environ["DOCUSEARCH_ADMIN_USERNAME"] == "jefa"
        assert os.environ["DOCUSEARCH_USER_PASSWORD_HASH"] == "scrypt$16384$8$1$abc$def"  # $ literal
        assert os.environ["DOCUSEARCH_CHUNK_SIZE"] == "150"  # el entorno manda
        assert os.environ["PATH"] == snapshot["PATH"]
    finally:
        os.environ.clear()
        os.environ.update(snapshot)


def test_hash_password_writes_env_file(tmp_path: Path, monkeypatch, capsys) -> None:
    env = tmp_path / ".env"
    env.write_text("DOCUSEARCH_MAX_UPLOAD_MB=20\nDOCUSEARCH_ADMIN_PASSWORD_HASH=viejo\n", encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO("una contraseña nueva y larga\n"))
    assert cli_main(["hash-password", "--stdin", "--env-file", str(env)]) == 0
    out = capsys.readouterr().out
    assert "scrypt$" not in out  # no se imprime el hash
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "DOCUSEARCH_MAX_UPLOAD_MB=20"
    hashes = [line.split("=", 1)[1] for line in lines if line.startswith("DOCUSEARCH_ADMIN_PASSWORD_HASH=")]
    assert len(hashes) == 1 and verify_password("una contraseña nueva y larga", hashes[0])
    monkeypatch.setattr("sys.stdin", io.StringIO("consulta solo lectura 99\n"))
    assert cli_main(["hash-password", "--stdin", "--env-file", str(env), "--role", "user"]) == 0
    assert "DOCUSEARCH_USER_PASSWORD_HASH=scrypt$" in env.read_text(encoding="utf-8")


def test_doctor_reports_missing_account_then_ok(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DOCUSEARCH_ADMIN_PASSWORD_HASH", raising=False)
    assert cli_main(["doctor", "--port", "1"]) == 1
    assert "Falta: Cuenta de Administrador" in capsys.readouterr().out
    from tests.auth_helpers import _hashes

    monkeypatch.setenv("DOCUSEARCH_ADMIN_PASSWORD_HASH", _hashes()[0])
    assert cli_main(["doctor", "--port", "1"]) == 0
    out = capsys.readouterr().out
    assert "Listo para iniciar." in out and "Modelo spaCy es_core_news_sm" in out


@pytest.mark.parametrize("script", ["instalar.ps1", "configurar-cuenta.ps1", "iniciar.ps1", "verificar.ps1"])
def test_powershell_scripts_do_not_weaken_policy_or_store_secrets(script: str) -> None:
    text = (Path(__file__).resolve().parents[1] / "scripts" / "windows" / script).read_text(encoding="utf-8")
    lowered = text.lower()
    assert "set-executionpolicy" not in lowered or "-scope process" in lowered
    assert "convertfrom-securestring" not in lowered and "password =" not in lowered
    assert "0.0.0.0" not in text


@pytest.mark.parametrize(
    "raw",
    [b"\xef\xbb\xbfclave-con-bom-12345\r\n", b"clave-con-bom-12345\n"],
)
def test_hash_password_stdin_ignores_powershell_bom(raw: bytes, monkeypatch, capsys) -> None:
    class _Stdin:
        encoding = "cp1252"
        buffer = io.BytesIO(raw)

    monkeypatch.setattr("sys.stdin", _Stdin())
    assert cli_main(["hash-password", "--stdin"]) == 0
    assert verify_password("clave-con-bom-12345", capsys.readouterr().out.strip())
