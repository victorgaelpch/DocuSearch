"""La matriz de trazabilidad cubre todos los requisitos académicos (DOC-24)."""

from __future__ import annotations

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"


def test_matrix_lists_every_requirement_once() -> None:
    text = (DOCS / "trazabilidad.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (RN?F\d\d) \|", text, flags=re.MULTILINE)
    expected = [f"RF{i:02d}" for i in range(1, 9)] + [f"RNF{i:02d}" for i in range(1, 8)]
    assert sorted(rows) == sorted(expected)


def test_adr_documents_missing_auth_and_oauth() -> None:
    adr = (DOCS / "adr" / "0001-entrega-web-v1.md").read_text(encoding="utf-8")
    assert "840eaaa" in adr
    assert "Sin autenticación" in adr
    assert "OAuth" in adr
