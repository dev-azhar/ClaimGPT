"""Tests for hybrid retrieval (BM25 + dense + RRF) in icd10_rag.

Covers the pure functions (`_tokenize`, `_rrf_fuse`, `_resolve_mode`)
and the public ``search_*`` API at the mode-routing level.

These tests don't load the real FAISS / BM25 indices — they patch the
internal rankers so they're fast and deterministic.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

# Make services/coding/app importable as `app.*`
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "coding"))
for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]

import pytest

from app import icd10_rag  # noqa: E402


class TestTokenize:
    def test_basic(self):
        assert icd10_rag._tokenize("Type 2 diabetes mellitus") == [
            "type", "2", "diabetes", "mellitus",
        ]

    def test_lowercases_and_strips_punct(self):
        assert icd10_rag._tokenize("Bell's palsy, idiopathic") == [
            "bell", "s", "palsy", "idiopathic",
        ]

    def test_handles_empty(self):
        assert icd10_rag._tokenize("") == []
        assert icd10_rag._tokenize(None) == []  # type: ignore[arg-type]

    def test_keeps_alphanumeric_codes(self):
        # ICD-10 codes embed digits — tokenizer keeps them as separate tokens.
        toks = icd10_rag._tokenize("E11.9 type 2 diabetes")
        assert "e11" in toks
        assert "9" in toks
        assert "type" in toks


class TestRrfFusion:
    def test_single_ranker_passes_through_order(self):
        ranking = [(1, 0.9), (2, 0.8), (3, 0.7)]
        fused = icd10_rag._rrf_fuse([ranking])
        # Order preserved.
        assert [idx for idx, _ in fused] == [1, 2, 3]

    def test_documents_appearing_in_both_rankers_promoted(self):
        # doc 5 is rank 0 in ranker A and rank 0 in ranker B → should
        # outrank doc 1 which is rank 0 in only one.
        a = [(5, 0.9), (1, 0.8)]
        b = [(5, 12.0), (2, 5.0)]
        fused = icd10_rag._rrf_fuse([a, b], k=60)
        order = [idx for idx, _ in fused]
        assert order[0] == 5

    def test_ignores_score_distribution(self):
        # Even with wildly different score scales, fusion uses ranks only.
        # Doc 7 is rank 0 in both rankers → must outrank doc 8 (rank 1
        # in both), regardless of how huge ranker-b's score 100.0 is.
        a = [(7, 0.999), (8, 0.5)]
        b = [(7, 0.001), (8, 100.0)]  # different scales, same ordering
        fused = icd10_rag._rrf_fuse([a, b])
        order = [idx for idx, _ in fused]
        assert order == [7, 8]

    def test_empty_rankings(self):
        assert icd10_rag._rrf_fuse([]) == []
        assert icd10_rag._rrf_fuse([[], []]) == []


class TestResolveMode:
    def test_unknown_mode_falls_back_to_dense(self):
        # When BM25 is unavailable the resolver must downgrade.
        with patch.object(icd10_rag, "is_bm25_available", return_value=False):
            assert icd10_rag._resolve_mode("garbage") == "dense"

    def test_explicit_dense_passes_through(self):
        with patch.object(icd10_rag, "is_bm25_available", return_value=True):
            assert icd10_rag._resolve_mode("dense") == "dense"

    def test_hybrid_falls_back_when_no_bm25(self):
        with patch.object(icd10_rag, "is_bm25_available", return_value=False):
            assert icd10_rag._resolve_mode("hybrid") == "dense"
            assert icd10_rag._resolve_mode("bm25") == "dense"

    def test_hybrid_passes_through_when_bm25_available(self):
        with patch.object(icd10_rag, "is_bm25_available", return_value=True):
            assert icd10_rag._resolve_mode("hybrid") == "hybrid"
            assert icd10_rag._resolve_mode("bm25") == "bm25"

    def test_none_uses_default(self):
        with patch.object(icd10_rag, "is_bm25_available", return_value=True), \
             patch.object(icd10_rag, "_DEFAULT_MODE", "hybrid"):
            assert icd10_rag._resolve_mode(None) == "hybrid"


class TestSearchModeRouting:
    """End-to-end test of the public API's mode routing.

    We patch the internal rankers so the test runs in milliseconds and
    doesn't require the real FAISS / BM25 indices.
    """

    def setup_method(self):
        # Ensure a clean cache and known module state.
        icd10_rag._search_icd10_rag_cached.cache_clear()
        icd10_rag._search_cpt_rag_cached.cache_clear()

    def _patch_indices(self):
        """Make the module appear ready and supply stub meta + indices."""
        meta = [
            {"code": "I10", "description": "Hypertension", "category": "Circulatory"},
            {"code": "J18.9", "description": "Pneumonia", "category": "Respiratory"},
            {"code": "E11.9", "description": "Type 2 diabetes", "category": "Endocrine"},
        ]
        # Sentinel non-None objects so is_rag_available() returns True.
        return [
            patch.object(icd10_rag, "_icd10_index", object()),
            patch.object(icd10_rag, "_icd10_meta", meta),
            patch.object(icd10_rag, "_icd10_bm25", object()),
        ]

    def test_dense_mode_uses_only_dense_ranker(self):
        patches = self._patch_indices()
        with patches[0], patches[1], patches[2], \
             patch.object(icd10_rag, "_dense_rank",
                          return_value=[(0, 0.9), (1, 0.4)]) as dmock, \
             patch.object(icd10_rag, "_bm25_rank") as bmock:
            hits = icd10_rag.search_icd10_rag("htn", max_results=2, mode="dense")

        assert dmock.called
        assert not bmock.called
        assert hits[0][0] == "I10"

    def test_bm25_mode_uses_only_bm25_ranker(self):
        patches = self._patch_indices()
        with patches[0], patches[1], patches[2], \
             patch.object(icd10_rag, "_dense_rank") as dmock, \
             patch.object(icd10_rag, "_bm25_rank",
                          return_value=[(2, 12.5)]) as bmock:
            hits = icd10_rag.search_icd10_rag("e11", max_results=5, mode="bm25")

        assert bmock.called
        assert not dmock.called
        assert len(hits) == 1
        assert hits[0][0] == "E11.9"

    def test_hybrid_mode_uses_both_rankers(self):
        patches = self._patch_indices()
        with patches[0], patches[1], patches[2], \
             patch.object(icd10_rag, "_dense_rank",
                          return_value=[(0, 0.9), (1, 0.4)]) as dmock, \
             patch.object(icd10_rag, "_bm25_rank",
                          return_value=[(0, 12.0), (2, 8.0)]) as bmock:
            hits = icd10_rag.search_icd10_rag("hypertension", max_results=3, mode="hybrid")

        assert dmock.called
        assert bmock.called
        # I10 (idx 0) appears at rank 0 in both rankers → top of fused list.
        assert hits[0][0] == "I10"

    def test_dense_min_score_gate_applies_only_in_dense_mode(self):
        patches = self._patch_indices()
        with patches[0], patches[1], patches[2], \
             patch.object(icd10_rag, "_dense_rank",
                          return_value=[(0, 0.20), (1, 0.50)]):  # 0 below cutoff
            hits = icd10_rag.search_icd10_rag(
                "x", max_results=5, min_score=0.3, mode="dense",
            )
            # Only 1 hit survives the gate (0.50 >= 0.3).
            assert [h[0] for h in hits] == ["J18.9"]

    def test_empty_query_returns_empty(self):
        for mode in ("dense", "bm25", "hybrid"):
            assert icd10_rag.search_icd10_rag("", mode=mode) == []
            assert icd10_rag.search_icd10_rag("   ", mode=mode) == []

    def test_invalid_mode_falls_back_silently(self):
        patches = self._patch_indices()
        with patches[0], patches[1], patches[2], \
             patch.object(icd10_rag, "_dense_rank",
                          return_value=[(0, 0.9)]) as dmock:
            hits = icd10_rag.search_icd10_rag("htn", mode="quantum")
        assert dmock.called
        assert hits[0][0] == "I10"


class TestBm25Available:
    def test_returns_false_when_unloaded(self):
        with patch.object(icd10_rag, "_icd10_bm25", None), \
             patch.object(icd10_rag, "_cpt_bm25", None), \
             patch.object(icd10_rag, "_load_indices", lambda: None):
            assert icd10_rag.is_bm25_available() is False

    def test_returns_true_when_loaded(self):
        with patch.object(icd10_rag, "_icd10_bm25", object()):
            assert icd10_rag.is_bm25_available() is True
