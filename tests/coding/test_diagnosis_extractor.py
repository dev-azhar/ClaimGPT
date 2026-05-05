"""Tests for the diagnosis-keyword extractor.

The LLM path is mocked so these tests run offline. The deterministic
fallback is exercised end-to-end with no mocks.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from services.coding.app import diagnosis_extractor as dx


@pytest.fixture(autouse=True)
def _clear_cache():
    dx.clear_cache()
    yield
    dx.clear_cache()


# ── needs_extraction -----------------------------------------------


class TestNeedsExtraction:
    def test_short_field_skips(self):
        assert dx.needs_extraction("Type 2 diabetes mellitus") is False

    def test_long_narrative_triggers(self):
        text = (
            "G3P1L1A1 39WKS pregnancy in labor full term normal delivery with "
            "episiotomy on 09/04/2026 vitals BP-121/83 mmHg P-88 /m RR-16 /m "
            "Temp afebrile general examination fair systemic exam clear"
        )
        assert dx.needs_extraction(text) is True

    def test_empty_skips(self):
        assert dx.needs_extraction("") is False
        assert dx.needs_extraction(None) is False  # type: ignore[arg-type]


# ── deterministic fallback ----------------------------------------


class TestDeterministicFallback:
    def test_extracts_section_after_diagnosis_header(self):
        text = (
            "Patient admitted with chest pain.\n"
            "Diagnosis: acute myocardial infarction with type 2 diabetes\n"
            "Procedures: PCI with drug eluting stent\n"
            "Medications: aspirin, clopidogrel"
        )
        with patch.object(dx, "_try_llm_extract", return_value=[]):
            terms = dx.extract_diagnosis_keywords(text * 5)  # force long
        assert any("myocardial" in t or "diabetes" in t for t in terms)
        # Should NOT bleed into procedures/medications sections
        assert not any("aspirin" in t for t in terms)
        assert not any("pci" in t for t in terms)

    def test_falls_back_to_vocab_when_no_header(self):
        text = (
            "39 weeks pregnancy in labor full term delivery with episiotomy "
            "patient stable BP 121/83 P 88 RR 16 examination fair systemic "
            "exam clear obstetric exam done plan continue monitoring "
            "additional notes for length filler"
        )
        with patch.object(dx, "_try_llm_extract", return_value=[]):
            terms = dx.extract_diagnosis_keywords(text)
        # Each term must mention something diagnosis-vocab-ish.
        joined = " ".join(terms).lower()
        assert any(k in joined for k in ("pregnancy", "labor", "delivery"))

    def test_strips_vital_noise(self):
        text = (
            "Diagnosis: hypertension and diabetes mellitus type 2 BP-160/100 "
            "P-88 RR-16 Temp-37.2 HBsAg-NR HIV-NR HBA1C-9.5 examination "
            "completed need long text here for the threshold trigger so we "
            "exceed the long narrative cutoff defined in the module config"
        )
        with patch.object(dx, "_try_llm_extract", return_value=[]):
            terms = dx.extract_diagnosis_keywords(text)
        for t in terms:
            assert "hbsag" not in t
            assert "hiv" not in t
            assert "121" not in t and "100" not in t

    def test_caps_at_max_terms(self):
        text = "Diagnosis: " + "; ".join(
            f"diabetes type {i}" for i in range(20)
        ) + ". " + "x" * 200
        with patch.object(dx, "_try_llm_extract", return_value=[]):
            terms = dx.extract_diagnosis_keywords(text, max_terms=3)
        assert len(terms) <= 3


# ── LLM path -------------------------------------------------------


class TestLlmPath:
    def test_uses_llm_output_when_available(self):
        text = "x" * 200  # long enough to trigger
        with patch.object(
            dx,
            "_try_llm_extract",
            return_value=["normal vaginal delivery with episiotomy", "term pregnancy"],
        ):
            terms = dx.extract_diagnosis_keywords(text, max_terms=5)
        assert "normal vaginal delivery with episiotomy" in terms
        assert "term pregnancy" in terms

    def test_falls_back_to_deterministic_when_llm_returns_empty(self):
        text = (
            "Diagnosis: type 2 diabetes mellitus with neuropathy. "
            "Patient also has hypertension. " + "x" * 200
        )
        with patch.object(dx, "_try_llm_extract", return_value=[]):
            terms = dx.extract_diagnosis_keywords(text)
        joined = " ".join(terms).lower()
        assert "diabetes" in joined or "hypertension" in joined

    def test_falls_back_when_llm_raises(self):
        text = "Diagnosis: pneumonia. " + "x" * 200
        def boom(_t, _n):
            raise RuntimeError("ollama unavailable")
        with patch.object(dx, "_try_llm_extract", side_effect=boom):
            # Should not raise
            terms = dx.extract_diagnosis_keywords(text)
        assert isinstance(terms, list)

    def test_llm_line_parser_strips_bullets_and_numbering(self):
        raw = (
            "1. Type 2 diabetes mellitus\n"
            "  - hypertension stage 2\n"
            "* acute myocardial infarction\n"
            "NONE\n"   # should be ignored
            "\n"
            "Type 2 diabetes mellitus\n"  # exact dup
        )
        out = dx._parse_llm_lines(raw, max_terms=10)
        assert "type 2 diabetes mellitus" in out
        assert "hypertension stage 2" in out
        assert "acute myocardial infarction" in out
        # NONE filtered, dup deduped
        assert "none" not in out
        assert len(out) == 3

    def test_llm_line_parser_drops_overlong_phrases(self):
        raw = "ok diagnosis\n" + ("x" * 200) + "\n"
        out = dx._parse_llm_lines(raw, max_terms=10)
        assert out == ["ok diagnosis"]


# ── caching --------------------------------------------------------


class TestCache:
    def test_repeat_call_hits_cache(self):
        text = "Diagnosis: appendicitis acute. " + "x" * 200
        calls = {"n": 0}

        def counting_llm(_t, _n):
            calls["n"] += 1
            return ["acute appendicitis"]

        with patch.object(dx, "_try_llm_extract", side_effect=counting_llm):
            a = dx.extract_diagnosis_keywords(text)
            b = dx.extract_diagnosis_keywords(text)
        assert a == b
        assert calls["n"] == 1
