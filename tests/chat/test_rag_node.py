"""Tests for services/chat/app/workflow/node.py::rag_node.

The rag_node is responsible for two retrieval passes:
  1. Query-based: top-K ICD-10 / CPT lookup using the latest user message.
  2. Entity-based: per-NER-entity lookup against the FAISS catalogs.

These tests mock out the underlying ``services.coding.app.icd10_rag`` so
they're fast and don't require the ~120MB FAISS indices on disk or the
``sentence-transformers`` model.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

# Make services/chat/app importable as `app.*` (consistent with test_llm.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]

import pytest

from services.chat.app.schemas import (
    ClaimContext,
    MedicalCodeModel,
    MedicalEntityModel,
    PredictionModel,
    ValidationModel,
)
from services.chat.app.workflow import node as node_mod


def _empty_ctx(entities=None) -> ClaimContext:
    """Build a minimal ClaimContext with the supplied entities."""
    return ClaimContext(
        claim_id="test-1",
        status="SUBMITTED",
        policy_id="POL-1",
        parsed_fields={},
        parsed_fields_by_document_type=None,
        full_ocr_text=None,
        relevant_text=None,
        ocr_page_count=0,
        ocr_by_document_type=None,
        predictions=[],
        validations=[],
        medical_codes=[],
        medical_entities=entities or [],
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestRagNodeAvailability:
    """rag_node should fail gracefully when the RAG module is unavailable."""

    def test_rag_unavailable_returns_none(self):
        with patch("services.coding.app.icd10_rag.is_rag_available", return_value=False):
            result = _run(node_mod.rag_node(
                {"chat_input": "fever", "claim_context": None}, config=None
            ))
        assert result == {"rag_results": None}

    def test_import_error_returns_none(self):
        # If the icd10_rag module itself can't be imported (e.g. faiss missing
        # in some deploy envs), rag_node should swallow the error.
        original_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def boom(name, *a, **kw):
            if name.startswith("services.coding.app.icd10_rag"):
                raise ImportError("simulated")
            return original_import(name, *a, **kw)

        with patch("builtins.__import__", side_effect=boom):
            result = _run(node_mod.rag_node(
                {"chat_input": "fever", "claim_context": None}, config=None
            ))
        assert result == {"rag_results": None}


class TestRagNodeQueryRetrieval:
    """Top-level query retrieval (no claim entities)."""

    def test_query_only_returns_icd10_and_cpt(self):
        with patch("services.coding.app.icd10_rag.is_rag_available", return_value=True), \
             patch("services.coding.app.icd10_rag.search_icd10_rag",
                   return_value=[("J18.9", "Pneumonia, unspecified", "Respiratory", 0.81)]) as icd_mock, \
             patch("services.coding.app.icd10_rag.search_cpt_rag",
                   return_value=[("71046", "Chest x-ray, 2 views", "Radiology", 0.42)]) as cpt_mock:
            result = _run(node_mod.rag_node(
                {"chat_input": "patient has pneumonia", "claim_context": None},
                config=None,
            ))

        rr = result["rag_results"]
        assert rr["query"] == "patient has pneumonia"
        assert len(rr["icd10"]) == 1
        assert rr["icd10"][0]["code"] == "J18.9"
        assert rr["icd10"][0]["score"] == 0.81
        assert rr["icd10"][0]["category"] == "Respiratory"
        assert len(rr["cpt"]) == 1
        assert rr["cpt"][0]["code"] == "71046"
        assert rr["entity_lookups"] == []
        # Both top-level searches should have been invoked once with the
        # raw user query.
        icd_mock.assert_called_once()
        cpt_mock.assert_called_once()

    def test_empty_query_skips_top_level_search(self):
        with patch("services.coding.app.icd10_rag.is_rag_available", return_value=True), \
             patch("services.coding.app.icd10_rag.search_icd10_rag") as icd_mock, \
             patch("services.coding.app.icd10_rag.search_cpt_rag") as cpt_mock:
            result = _run(node_mod.rag_node(
                {"chat_input": "   ", "claim_context": None},
                config=None,
            ))

        rr = result["rag_results"]
        assert rr["query"] == ""
        assert rr["icd10"] == []
        assert rr["cpt"] == []
        # No claim, no entities → nothing to look up.
        icd_mock.assert_not_called()
        cpt_mock.assert_not_called()


class TestRagNodeEntityLookups:
    """Per-NER-entity ICD-10 / CPT routing."""

    def test_diagnosis_routes_to_icd10(self):
        cc = _empty_ctx(entities=[
            MedicalEntityModel(text="Type 2 diabetes mellitus", type="DIAGNOSIS", confidence=0.9),
        ])

        def _icd_lookup(text, max_results=1, **_):
            assert text == "Type 2 diabetes mellitus"
            assert max_results == 1
            return [("E11.9", "Type 2 diabetes mellitus without complications", "Endocrine", 0.91)]

        with patch("services.coding.app.icd10_rag.is_rag_available", return_value=True), \
             patch("services.coding.app.icd10_rag.search_icd10_rag", side_effect=_icd_lookup), \
             patch("services.coding.app.icd10_rag.search_cpt_rag", return_value=[]) as cpt_mock:
            result = _run(node_mod.rag_node(
                {"chat_input": "", "claim_context": cc}, config=None
            ))

        lookups = result["rag_results"]["entity_lookups"]
        assert len(lookups) == 1
        assert lookups[0]["code_system"] == "ICD-10"
        assert lookups[0]["code"] == "E11.9"
        assert lookups[0]["entity_type"] == "DIAGNOSIS"
        # Procedure-side search should not have been called for a diagnosis.
        cpt_mock.assert_not_called()

    def test_procedure_routes_to_cpt(self):
        cc = _empty_ctx(entities=[
            MedicalEntityModel(text="Knee arthroscopy", type="PROCEDURE", confidence=0.88),
        ])
        with patch("services.coding.app.icd10_rag.is_rag_available", return_value=True), \
             patch("services.coding.app.icd10_rag.search_icd10_rag", return_value=[]) as icd_mock, \
             patch("services.coding.app.icd10_rag.search_cpt_rag",
                   return_value=[("29881", "Arthroscopy, knee", "Surgery", 0.88)]):
            result = _run(node_mod.rag_node(
                {"chat_input": "", "claim_context": cc}, config=None
            ))

        lookups = result["rag_results"]["entity_lookups"]
        assert len(lookups) == 1
        assert lookups[0]["code_system"] == "CPT"
        assert lookups[0]["code"] == "29881"
        # Diagnosis-side search should not have been called.
        icd_mock.assert_not_called()

    def test_dedupes_case_insensitive(self):
        cc = _empty_ctx(entities=[
            MedicalEntityModel(text="Acute appendicitis", type="DIAGNOSIS", confidence=0.9),
            MedicalEntityModel(text="acute APPENDICITIS", type="DIAGNOSIS", confidence=0.85),  # dup
            MedicalEntityModel(text="Acute Appendicitis", type="DIAGNOSIS", confidence=0.92),  # dup
        ])
        calls = []

        def _icd_lookup(text, max_results=1, **_):
            calls.append(text)
            return [("K35.80", "Unspecified acute appendicitis", "Digestive", 0.85)]

        with patch("services.coding.app.icd10_rag.is_rag_available", return_value=True), \
             patch("services.coding.app.icd10_rag.search_icd10_rag", side_effect=_icd_lookup), \
             patch("services.coding.app.icd10_rag.search_cpt_rag", return_value=[]):
            result = _run(node_mod.rag_node(
                {"chat_input": "", "claim_context": cc}, config=None
            ))

        # Only one lookup should have been performed even though three
        # entities have the same (case-insensitive) text.
        assert len(calls) == 1
        assert len(result["rag_results"]["entity_lookups"]) == 1

    def test_skips_empty_text(self):
        cc = _empty_ctx(entities=[
            MedicalEntityModel(text="", type="DIAGNOSIS", confidence=0.5),
            MedicalEntityModel(text="   ", type="PROCEDURE", confidence=0.5),
            MedicalEntityModel(text="Pneumonia", type="DIAGNOSIS", confidence=0.9),
        ])
        with patch("services.coding.app.icd10_rag.is_rag_available", return_value=True), \
             patch("services.coding.app.icd10_rag.search_icd10_rag",
                   return_value=[("J18.9", "Pneumonia, unspecified", "Respiratory", 0.8)]) as icd_mock, \
             patch("services.coding.app.icd10_rag.search_cpt_rag", return_value=[]):
            result = _run(node_mod.rag_node(
                {"chat_input": "", "claim_context": cc}, config=None
            ))

        # Only the non-empty 'Pneumonia' entity should produce a lookup.
        assert icd_mock.call_count == 1
        assert len(result["rag_results"]["entity_lookups"]) == 1

    def test_skips_unhandled_entity_type(self):
        cc = _empty_ctx(entities=[
            MedicalEntityModel(text="aspirin", type="DRUG", confidence=0.9),  # not routed
            MedicalEntityModel(text="cough", type="SYMPTOM", confidence=0.7),  # → ICD-10
        ])
        with patch("services.coding.app.icd10_rag.is_rag_available", return_value=True), \
             patch("services.coding.app.icd10_rag.search_icd10_rag",
                   return_value=[("R05.9", "Cough, unspecified", "Symptoms", 0.85)]), \
             patch("services.coding.app.icd10_rag.search_cpt_rag", return_value=[]):
            result = _run(node_mod.rag_node(
                {"chat_input": "", "claim_context": cc}, config=None
            ))

        lookups = result["rag_results"]["entity_lookups"]
        # Only the symptom is routed; 'aspirin' (DRUG) is skipped.
        assert len(lookups) == 1
        assert lookups[0]["entity_text"] == "cough"


class TestRagNodeCombined:
    """End-to-end shape: query + entities together."""

    def test_query_and_entities_both_populated(self):
        cc = _empty_ctx(entities=[
            MedicalEntityModel(text="hypertension", type="CONDITION", confidence=0.9),
        ])
        with patch("services.coding.app.icd10_rag.is_rag_available", return_value=True), \
             patch("services.coding.app.icd10_rag.search_icd10_rag",
                   side_effect=[
                       # First call (query) returns top-5
                       [("I10", "Essential hypertension", "Circulatory", 0.9)],
                       # Second call (entity lookup) returns top-1
                       [("I10", "Essential hypertension", "Circulatory", 0.95)],
                   ]), \
             patch("services.coding.app.icd10_rag.search_cpt_rag", return_value=[]):
            result = _run(node_mod.rag_node(
                {"chat_input": "what code for high BP?", "claim_context": cc},
                config=None,
            ))

        rr = result["rag_results"]
        assert rr["query"] == "what code for high BP?"
        assert len(rr["icd10"]) == 1
        assert len(rr["entity_lookups"]) == 1
        assert rr["entity_lookups"][0]["entity_text"] == "hypertension"


class TestRagNodeCodingConsistency:
    """The ``coding_consistency`` block compares submitted vs RAG-suggested codes."""

    def _ctx_with_codes(self, codes, entities=None):
        ctx = _empty_ctx(entities=entities)
        ctx.medical_codes = list(codes)
        return ctx

    def test_unsupported_codes_flagged(self):
        # Claim has E11.9 (diabetes) but RAG suggests J18.9 (pneumonia)
        # → E11.9 should be flagged as unsupported by retrieval.
        cc = self._ctx_with_codes(
            codes=[
                MedicalCodeModel(code="E11.9", code_type="ICD10", description="Diabetes", confidence=0.9),
            ],
            entities=[],
        )
        with patch("services.coding.app.icd10_rag.is_rag_available", return_value=True), \
             patch("services.coding.app.icd10_rag.search_icd10_rag",
                   return_value=[("J18.9", "Pneumonia", "Respiratory", 0.8)]), \
             patch("services.coding.app.icd10_rag.search_cpt_rag", return_value=[]):
            result = _run(node_mod.rag_node(
                {"chat_input": "patient has cough and fever", "claim_context": cc},
                config=None,
            ))

        cc_check = result["rag_results"]["coding_consistency"]
        assert cc_check["submitted_icd10"] == ["E11.9"]
        assert cc_check["icd10_unsupported_by_retrieval"] == ["E11.9"]
        assert "J18.9" in cc_check["icd10_missing_from_claim"]

    def test_supported_codes_not_flagged(self):
        # Claim's submitted code matches what RAG retrieves → not flagged.
        cc = self._ctx_with_codes(
            codes=[
                MedicalCodeModel(code="J18.9", code_type="ICD-10", description="Pneumonia", confidence=0.9),
            ],
        )
        with patch("services.coding.app.icd10_rag.is_rag_available", return_value=True), \
             patch("services.coding.app.icd10_rag.search_icd10_rag",
                   return_value=[("J18.9", "Pneumonia, unspecified", "Respiratory", 0.81)]), \
             patch("services.coding.app.icd10_rag.search_cpt_rag", return_value=[]):
            result = _run(node_mod.rag_node(
                {"chat_input": "pneumonia", "claim_context": cc}, config=None,
            ))

        cc_check = result["rag_results"]["coding_consistency"]
        assert cc_check["icd10_unsupported_by_retrieval"] == []
        assert cc_check["icd10_missing_from_claim"] == []

    def test_cpt_separation(self):
        # CPT submitted on claim should populate submitted_cpt, not submitted_icd10.
        cc = self._ctx_with_codes(
            codes=[
                MedicalCodeModel(code="29881", code_type="CPT", description="Knee scope", confidence=0.9),
            ],
        )
        with patch("services.coding.app.icd10_rag.is_rag_available", return_value=True), \
             patch("services.coding.app.icd10_rag.search_icd10_rag", return_value=[]), \
             patch("services.coding.app.icd10_rag.search_cpt_rag",
                   return_value=[("29881", "Arthroscopy, knee", "Surgery", 0.88)]):
            result = _run(node_mod.rag_node(
                {"chat_input": "knee arthroscopy", "claim_context": cc}, config=None,
            ))

        cc_check = result["rag_results"]["coding_consistency"]
        assert cc_check["submitted_cpt"] == ["29881"]
        assert cc_check["submitted_icd10"] == []
        assert cc_check["cpt_unsupported_by_retrieval"] == []

    def test_no_claim_codes_means_empty_submitted(self):
        cc = _empty_ctx()  # no codes, no entities
        with patch("services.coding.app.icd10_rag.is_rag_available", return_value=True), \
             patch("services.coding.app.icd10_rag.search_icd10_rag",
                   return_value=[("R50.9", "Fever, unspecified", "Symptoms", 0.7)]), \
             patch("services.coding.app.icd10_rag.search_cpt_rag", return_value=[]):
            result = _run(node_mod.rag_node(
                {"chat_input": "fever", "claim_context": cc}, config=None,
            ))

        cc_check = result["rag_results"]["coding_consistency"]
        assert cc_check["submitted_icd10"] == []
        assert cc_check["submitted_cpt"] == []
        assert cc_check["icd10_unsupported_by_retrieval"] == []
        # RAG suggestion shows up as missing from the (empty) claim.
        assert cc_check["icd10_missing_from_claim"] == ["R50.9"]

    def test_entity_lookup_codes_count_as_supported(self):
        # Submitted code matches the per-entity top-1 RAG hit (not the
        # query-level results). It should still be considered supported.
        cc = self._ctx_with_codes(
            codes=[
                MedicalCodeModel(code="K35.80", code_type="ICD10", description="Appendicitis", confidence=0.9),
            ],
            entities=[
                MedicalEntityModel(text="acute appendicitis", type="DIAGNOSIS", confidence=0.9),
            ],
        )
        with patch("services.coding.app.icd10_rag.is_rag_available", return_value=True), \
             patch("services.coding.app.icd10_rag.search_icd10_rag",
                   side_effect=[
                       [],  # query-level: no hits
                       [("K35.80", "Acute appendicitis", "Digestive", 0.92)],  # entity lookup
                   ]), \
             patch("services.coding.app.icd10_rag.search_cpt_rag", return_value=[]):
            result = _run(node_mod.rag_node(
                {"chat_input": "is the diagnosis correct?", "claim_context": cc},
                config=None,
            ))

        cc_check = result["rag_results"]["coding_consistency"]
        assert cc_check["icd10_unsupported_by_retrieval"] == []
        assert cc_check["icd10_missing_from_claim"] == []
