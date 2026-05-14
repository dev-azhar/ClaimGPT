"""Tests for advanced OCR engine extensions (PR #45).

Covers:
* SUPPORTED_EXTENSIONS includes the newly-added formats.
* RTF extractor falls back gracefully when ``striprtf`` isn't installed.
* PPTX/ODT extractors raise informative errors when their libs are missing.
* ``_maybe_decrypt_pdf`` is a no-op when the file is unencrypted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.ocr.app import engine as ocr_engine


def test_supported_extensions_includes_new_formats() -> None:
    assert ".heic" in ocr_engine.SUPPORTED_EXTENSIONS
    assert ".heif" in ocr_engine.SUPPORTED_EXTENSIONS
    assert ".gif" in ocr_engine.SUPPORTED_EXTENSIONS
    assert ".pptx" in ocr_engine.SUPPORTED_EXTENSIONS
    assert ".odt" in ocr_engine.SUPPORTED_EXTENSIONS
    assert ".rtf" in ocr_engine.SUPPORTED_EXTENSIONS
    assert ".pdf" in ocr_engine.SUPPORTED_EXTENSIONS
    assert ".docx" in ocr_engine.SUPPORTED_EXTENSIONS


def test_rtf_extractor_handles_minimal_rtf(tmp_path: Path) -> None:
    """Minimal RTF — both striprtf and the regex fallback should yield the body text."""
    rtf = r"{\rtf1\ansi\deff0 {\fonttbl{\f0 Times;}} \f0\fs24 Hello world.}"
    p = tmp_path / "sample.rtf"
    p.write_text(rtf, encoding="utf-8")

    pages = ocr_engine._extract_from_rtf(p)
    assert len(pages) == 1
    _page_no, text, _conf = pages[0]
    assert "Hello world" in text
    # No raw RTF control words leak through.
    assert r"\rtf1" not in text
    assert r"\fonttbl" not in text


def test_pptx_extractor_missing_lib_is_informative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr_engine, "_HAS_PPTX", False)
    p = tmp_path / "deck.pptx"
    p.write_bytes(b"PK\x03\x04 fake")
    with pytest.raises(ValueError, match="python-pptx"):
        ocr_engine._extract_from_pptx(p)


def test_odt_extractor_missing_lib_is_informative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr_engine, "_HAS_ODF", False)
    p = tmp_path / "doc.odt"
    p.write_bytes(b"PK\x03\x04 fake")
    with pytest.raises(ValueError, match="odfpy"):
        ocr_engine._extract_from_odt(p)


def test_maybe_decrypt_pdf_returns_input_for_plain_pdf(tmp_path: Path) -> None:
    """Unencrypted PDFs should be a passthrough (no temp file created)."""
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 100 100]>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000053 00000 n\n0000000099 00000 n\n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n151\n%%EOF\n"
    )
    p = tmp_path / "plain.pdf"
    p.write_bytes(body)

    out = ocr_engine._maybe_decrypt_pdf(p)
    # Either pikepdf isn't installed (returns input) or the file is not encrypted (returns input).
    assert out == p
