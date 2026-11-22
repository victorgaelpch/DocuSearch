"""OCR de PDF escaneados (DOC-23).

Las pruebas unitarias no necesitan Tesseract. Las de integración generan en
memoria un PDF **solo de imagen** (texto rasterizado) y usan el Tesseract del
sistema; se omiten si no está instalado.
"""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.app.documents import ocr as ocr_module
from backend.app.documents.models import ExtractionStatus
from backend.app.documents.ocr import OcrConfig, TesseractOcr, find_tessdata, get_ocr
from backend.app.documents.readers import extract_document
from tests.auth_helpers import admin_client
from tests.synthetic import scanned_pdf

TESSDATA = find_tessdata()
needs_tesseract = pytest.mark.skipif(TESSDATA is None, reason="Tesseract no está instalado")

TEXT_PAGE_2 = "El astrolabio era un instrumento usado por los navegantes para medir la altura de los astros."


_scanned_pdf = scanned_pdf


@pytest.fixture(autouse=True)
def _fresh_ocr_cache(monkeypatch):
    monkeypatch.setattr(ocr_module, "_cached", None)
    yield
    ocr_module._cached = None


# --- configuración y selección de idioma -----------------------------------


def test_config_from_env(monkeypatch) -> None:
    assert OcrConfig.from_env() == OcrConfig()
    monkeypatch.setenv("DOCUSEARCH_OCR", "off")
    monkeypatch.setenv("DOCUSEARCH_OCR_LANG", "eng")
    monkeypatch.setenv("DOCUSEARCH_OCR_DPI", "200")
    monkeypatch.setenv("DOCUSEARCH_OCR_MAX_PAGES", "3")
    assert OcrConfig.from_env() == OcrConfig(enabled=False, languages="eng", dpi=200, max_pages=3)
    monkeypatch.setenv("DOCUSEARCH_OCR", "siempre")
    with pytest.raises(ValueError):
        OcrConfig.from_env()
    monkeypatch.setenv("DOCUSEARCH_OCR", "auto")
    monkeypatch.setenv("DOCUSEARCH_OCR_DPI", "cero")
    with pytest.raises(ValueError):
        OcrConfig.from_env()
    monkeypatch.setenv("DOCUSEARCH_OCR_DPI", "0")
    with pytest.raises(ValueError):
        OcrConfig.from_env()


def _fake_tessdata(tmp_path: Path, languages: list[str]) -> Path:
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir(parents=True)
    for language in languages:
        (tessdata / f"{language}.traineddata").write_bytes(b"x")
    return tessdata


def test_resolve_language_uses_installed_and_warns(tmp_path: Path) -> None:
    tessdata = _fake_tessdata(tmp_path, ["eng", "osd"])
    ocr = TesseractOcr(tessdata, OcrConfig(languages="spa+eng"))
    assert ocr.available_languages == ["eng"]
    language, warnings = ocr.resolve_language()
    assert language == "eng" and "spa" in warnings[0]
    assert TesseractOcr(_fake_tessdata(tmp_path / "b", ["spa", "eng"]), OcrConfig()).resolve_language() == ("spa+eng", [])
    # ninguno de los pedidos instalado: se usa uno disponible
    assert TesseractOcr(tessdata, OcrConfig(languages="fra")).resolve_language()[0] == "eng"
    empty = _fake_tessdata(tmp_path / "c", ["osd"])
    assert TesseractOcr(empty, OcrConfig()).resolve_language()[0] == ""


def test_find_tessdata_honours_environment(tmp_path: Path, monkeypatch) -> None:
    tessdata = _fake_tessdata(tmp_path, ["eng"])
    monkeypatch.setenv("DOCUSEARCH_TESSDATA", str(tessdata))
    assert find_tessdata() == tessdata
    monkeypatch.setenv("DOCUSEARCH_TESSDATA", str(tmp_path))  # carpeta padre
    assert find_tessdata() == tessdata


def test_get_ocr_disabled_or_missing(monkeypatch) -> None:
    monkeypatch.setenv("DOCUSEARCH_OCR", "off")
    assert get_ocr() is None
    monkeypatch.setenv("DOCUSEARCH_OCR", "auto")
    monkeypatch.setattr(ocr_module, "find_tessdata", lambda: None)
    assert get_ocr() is None


class _FakePage:
    def __init__(self, text: str, fail: bool = False) -> None:
        self.text, self.fail = text, fail

    def get_textpage_ocr(self, **kwargs):
        if self.fail:
            raise RuntimeError("tesseract murió")
        assert kwargs["full"] is True and kwargs["language"] == "eng"
        return "tp"

    def get_text(self, kind, textpage=None):
        return self.text


def test_recognize_limits_pages_and_survives_page_errors(tmp_path: Path) -> None:
    ocr = TesseractOcr(_fake_tessdata(tmp_path, ["eng"]), OcrConfig(languages="eng", max_pages=2))
    document = [_FakePage("uno"), _FakePage("", fail=True), _FakePage("tres")]
    outcome = ocr.recognize(document, [1, 2, 3])
    assert outcome.texts == {1: "uno"}
    assert any("limitado a 2 de 3" in w for w in outcome.warnings)
    assert any("página 2" in w for w in outcome.warnings)
    assert outcome.metadata({"engine": "tesseract"})["pages"] == [1]
    no_language = TesseractOcr(_fake_tessdata(tmp_path / "x", ["osd"]), OcrConfig())
    assert no_language.recognize(document, [1]).texts == {}


def test_without_ocr_scanned_pdf_stays_needs_ocr(monkeypatch) -> None:
    monkeypatch.setenv("DOCUSEARCH_OCR", "off")
    result = extract_document(_scanned_pdf([TEXT_PAGE_2]), "escaneado.pdf")
    assert result.status is ExtractionStatus.NEEDS_OCR and "ocr" not in result.metadata


# --- integración con Tesseract real ------------------------------------------


@needs_tesseract
def test_scanned_pdf_is_recognized_with_page_provenance(monkeypatch) -> None:
    monkeypatch.setenv("DOCUSEARCH_OCR_LANG", "eng")  # el único idioma garantizado en el equipo de prueba
    result = extract_document(_scanned_pdf([None, TEXT_PAGE_2]), "escaneado.pdf")
    assert result.status is ExtractionStatus.EXTRACTED
    assert "astrolabio" in result.text and "navegantes" in result.text
    page_2 = [s for s in result.sections if s.page_number == 2]
    assert page_2 and "astrolabio" in page_2[0].text
    ocr_meta = result.metadata["ocr"]
    assert ocr_meta["engine"] == "tesseract" and ocr_meta["pages"] == [2] and ocr_meta["language"] == "eng"
    assert result.metadata["pages_without_text"] == [1]  # la página en blanco sigue sin texto


@needs_tesseract
def test_mixed_pdf_only_ocrs_pages_without_text(monkeypatch) -> None:
    monkeypatch.setenv("DOCUSEARCH_OCR_LANG", "eng")
    digital = pymupdf.open()
    digital.new_page().insert_text((72, 72), "Pagina digital con capa de texto sobre volcanes.", fontsize=12)
    scanned = pymupdf.open(stream=_scanned_pdf([TEXT_PAGE_2]), filetype="pdf")
    digital.insert_pdf(scanned)
    result = extract_document(digital.tobytes(), "mixto.pdf")
    assert result.status is ExtractionStatus.EXTRACTED and result.metadata["ocr"]["pages"] == [2]
    assert "volcanes" in result.sections[0].text and "astrolabio" in result.sections[1].text


@needs_tesseract
def test_upload_scanned_pdf_is_searchable_and_cli_processes_pending(tmp_path: Path, monkeypatch, capsys, lexical_pipeline) -> None:
    from backend.app.cli import main as cli_main
    from backend.app.config import Settings
    from backend.app.main import create_app

    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCUSEARCH_OCR_LANG", "eng")
    settings = Settings.from_env()

    # 1) sin OCR: se carga como needs_ocr y no se encuentra
    monkeypatch.setenv("DOCUSEARCH_OCR", "off")
    client = admin_client(settings)
    body = client.post("/documents", files={"file": ("escaneado.pdf", _scanned_pdf([None, TEXT_PAGE_2]))}).json()
    assert body["extraction_status"] == "needs_ocr"
    assert client.get("/search", params={"q": "astrolabio"}).json()["total"] == 0
    assert cli_main(["ocr"]) == 1  # OCR desactivado: error claro

    # 2) el comando ocr reprocesa los pendientes
    monkeypatch.setenv("DOCUSEARCH_OCR", "auto")
    assert cli_main(["ocr"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["pending"] == 1 and report["recognized"] == [body["doc_id"]]
    detail = client.get(f"/documents/{body['doc_id']}").json()
    assert detail["extraction_status"] == "extracted" and detail["metadata"]["ocr"]["pages"] == [2]
    hits = client.get("/search", params={"q": "astrolabio"}).json()["results"]
    assert hits and hits[0]["doc_id"] == body["doc_id"] and hits[0]["page_start"] == 2

    # 3) con OCR activo, una carga nueva se reconoce directamente
    other = client.post("/documents", files={"file": ("otro.pdf", _scanned_pdf(["Los volcanes expulsan lava y ceniza."]))}).json()
    assert other["extraction_status"] == "extracted" and other["chunk_count"] >= 1
    assert cli_main(["ocr"]) == 0 and json.loads(capsys.readouterr().out)["pending"] == 0


# --- idiomas instalados localmente (data/tessdata) ---------------------------


def test_install_languages_verifies_hash_and_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    import hashlib

    from backend.app.documents import tessdata
    from backend.app.documents.tessdata import TessdataError, install_languages

    payload = b"modelo falso"
    fake = tessdata.TessdataSource("tessdata_fast", "c" * 40, {"spa": hashlib.sha256(payload).hexdigest()})
    monkeypatch.setitem(tessdata.SOURCES, "fast", fake)
    calls: list[str] = []
    monkeypatch.setattr(tessdata, "_download", lambda url: calls.append(url) or payload)

    report = install_languages(tmp_path / "td", ["spa"])
    assert report["languages"]["spa"]["status"] == "installed"
    assert calls == [f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{'c' * 40}/spa.traineddata"]
    assert (tmp_path / "td" / "spa.traineddata").read_bytes() == payload
    assert install_languages(tmp_path / "td", ["spa"])["languages"]["spa"]["status"] == "already_installed"
    assert len(calls) == 1

    monkeypatch.setattr(tessdata, "_download", lambda url: b"otro contenido")
    (tmp_path / "td" / "spa.traineddata").write_bytes(b"corrupto")
    with pytest.raises(TessdataError, match="SHA-256"):
        install_languages(tmp_path / "td", ["spa"])
    assert not list((tmp_path / "td").glob(".tmp-*"))
    with pytest.raises(TessdataError, match="sin hash"):
        install_languages(tmp_path / "td", ["klingon"])
    with pytest.raises(TessdataError, match="variante"):
        install_languages(tmp_path / "td", ["spa"], variant="ultra")

    def offline(url):
        raise OSError("sin red")

    monkeypatch.setattr(tessdata, "_download", offline)
    with pytest.raises(TessdataError, match="sin red"):
        install_languages(tmp_path / "td", ["spa"])


def test_pinned_sources_are_complete() -> None:
    from backend.app.documents.tessdata import SOURCES

    for source in SOURCES.values():
        assert len(source.commit) == 40 and set(source.sha256) == {"spa", "eng"}
        assert all(len(h) == 64 for h in source.sha256.values())


def test_find_tessdata_prefers_project_data_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DOCUSEARCH_TESSDATA", raising=False)
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(tmp_path / "data"))
    local = tmp_path / "data" / "tessdata"
    local.mkdir(parents=True)
    (local / "spa.traineddata").write_bytes(b"x")
    assert find_tessdata() == local.resolve()


def test_cli_tessdata(tmp_path: Path, monkeypatch, capsys) -> None:
    from backend.app.cli import main as cli_main
    from backend.app.documents import tessdata

    monkeypatch.setenv("DOCUSEARCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(tessdata, "install_languages", lambda dest, langs, variant: {"destination": str(dest), "languages": langs})
    assert cli_main(["tessdata", "--languages", "spa"]) == 0
    assert json.loads(capsys.readouterr().out)["languages"] == ["spa"]

    def fail(dest, langs, variant):
        raise tessdata.TessdataError("boom")

    monkeypatch.setattr(tessdata, "install_languages", fail)
    assert cli_main(["tessdata"]) == 1


SPANISH = "El niño pequeño aprendió música en la montaña y la fotosíntesis convierte la energía solar."


@pytest.mark.skipif(
    TESSDATA is None or not (Path(TESSDATA) / "spa.traineddata").is_file(),
    reason="requiere el idioma español de Tesseract (python -m backend.app.cli tessdata)",
)
def test_spanish_model_keeps_accents_and_enye(monkeypatch) -> None:
    monkeypatch.setenv("DOCUSEARCH_TESSDATA", str(TESSDATA))
    monkeypatch.setenv("DOCUSEARCH_OCR_LANG", "spa")
    result = extract_document(_scanned_pdf([SPANISH]), "es.pdf")
    words = result.text.split()
    for expected in ("niño", "pequeño", "aprendió", "música", "fotosíntesis", "energía"):
        assert expected in words, (expected, result.text)
    # error real observado: a final de línea une "montaña" con la "y" siguiente
    # ("montañay"); la ñ se reconoce igualmente
    assert "montaña" in result.text
    assert result.metadata["ocr"]["language"] == "spa"
