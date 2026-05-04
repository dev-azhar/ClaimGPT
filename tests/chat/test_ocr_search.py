"""Tests for services/chat/app/ocr_search.py.

Covers:
  * _chunks() — overlapping window correctness
  * _hash_text() — stability + uniqueness
  * _embed_chunks cache — second call doesn't re-encode
  * semantic_chunk_search() — top-k selection, document-order output,
    short-circuit on tiny documents, graceful None on model failure
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]

from services.chat.app import ocr_search  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts with an empty chunk cache."""
    ocr_search.clear_chunk_cache()
    yield
    ocr_search.clear_chunk_cache()


class TestChunks:
    def test_empty_text_returns_empty(self):
        assert ocr_search._chunks("", 100, 20) == []

    def test_simple_split(self):
        text = "abcdefghij" * 10  # 100 chars
        result = ocr_search._chunks(text, 30, 0)
        # step=30, no overlap -> chunks at 0, 30, 60, 90
        offsets = [off for off, _ in result]
        assert offsets == [0, 30, 60, 90]
        assert len(result[0][1]) == 30
        # Last chunk is the tail (10 chars)
        assert len(result[-1][1]) == 10

    def test_overlap_preserves_context(self):
        text = "x" * 100
        result = ocr_search._chunks(text, 40, 10)
        # step = 40 - 10 = 30 → starts at 0, 30, 60, 90
        offsets = [off for off, _ in result]
        assert offsets == [0, 30, 60, 90]

    def test_strips_whitespace_only_chunks(self):
        text = "hello" + " " * 100 + "world"
        result = ocr_search._chunks(text, 20, 0)
        # The middle pure-whitespace window should be skipped.
        for _, chunk in result:
            assert chunk.strip() != ""


class TestHashText:
    def test_stable_across_calls(self):
        assert ocr_search._hash_text("foo") == ocr_search._hash_text("foo")

    def test_different_inputs_different_hashes(self):
        assert ocr_search._hash_text("a") != ocr_search._hash_text("b")

    def test_returns_16_chars(self):
        assert len(ocr_search._hash_text("anything")) == 16


class _FakeModel:
    """Stand-in for SentenceTransformer.

    Every call to ``encode`` returns deterministic but content-aware
    vectors so the top-k math actually exercises the code path.

    Strategy: vector[i] = sum of ord(c) for c in text % some basis. That
    way two texts containing the same characters score similarly.
    """

    def __init__(self):
        self.encode_calls = 0

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False, batch_size=64):
        self.encode_calls += 1
        out = []
        for t in texts:
            v = np.zeros(8, dtype=np.float32)
            for c in t.lower():
                v[ord(c) % 8] += 1.0
            n = np.linalg.norm(v) or 1.0
            out.append(v / n if normalize_embeddings else v)
        return np.array(out, dtype=np.float32)


class TestSemanticChunkSearch:
    def test_returns_none_for_empty_inputs(self):
        assert ocr_search.semantic_chunk_search("", "x") is None
        assert ocr_search.semantic_chunk_search("x", "") is None
        assert ocr_search.semantic_chunk_search("x", "   ") is None

    def test_short_text_returned_as_is(self):
        text = "Patient diagnosed with hypertension. Prescribed amlodipine."
        out = ocr_search.semantic_chunk_search(text, "what diagnosis?", max_chars=12000)
        assert out == text  # no chunking needed for short docs

    def test_returns_none_when_model_unavailable(self):
        long_text = "x" * 50_000
        with patch.object(ocr_search, "_get_model", return_value=None):
            assert ocr_search.semantic_chunk_search(long_text, "anything") is None

    def test_top_k_selected_by_similarity(self):
        # Build a long document where one section is rich in the query
        # tokens and the rest is filler. Semantic search should pick it.
        filler = ("alpha " * 500 + "beta " * 500 + "gamma " * 500)
        # Repeat the target so the chunk that contains it is dominated
        # by query tokens (the fake encoder is character-distribution
        # based, so a single 26-char target gets swamped by 300 chars
        # of filler around it).
        target = "diabetic neuropathy " * 20
        full_text = filler + " " + target + " " + filler
        assert len(full_text) > 12000

        with patch.object(ocr_search, "_get_model", return_value=_FakeModel()):
            out = ocr_search.semantic_chunk_search(
                full_text,
                "diabetic neuropathy",
                max_chars=2000,
                chunk_size=200,
                overlap=20,
                top_k=3,
            )

        assert out is not None
        # The target chunk's character distribution most closely matches
        # the query under the fake encoder, so it must be in the output.
        assert "neuropathy" in out.lower()

    def test_caches_chunk_embeddings(self):
        long_text = ("alpha beta gamma " * 1000)  # ~17k chars → triggers chunking
        fake = _FakeModel()
        with patch.object(ocr_search, "_get_model", return_value=fake):
            ocr_search.semantic_chunk_search(long_text, "alpha", max_chars=2000)
            calls_after_first = fake.encode_calls
            ocr_search.semantic_chunk_search(long_text, "beta", max_chars=2000)
            calls_after_second = fake.encode_calls

        # First call: 1 batched encode for chunks + 1 for the query = 2.
        # Second call hits the chunk cache → only the query is re-encoded.
        assert calls_after_first == 2
        assert calls_after_second == calls_after_first + 1

    def test_chunks_returned_in_document_order(self):
        # Two distinct relevant chunks at known offsets — output must
        # preserve their original order, not sort by score.
        long_text = (
            "PRESCRIPTION amlodipine 5mg "  # ~30 chars
            + ("filler " * 2000)             # ~14000 chars filler
            + "DIAGNOSIS hypertension"       # at far end
        )
        assert len(long_text) > 12000

        fake = _FakeModel()
        with patch.object(ocr_search, "_get_model", return_value=fake):
            out = ocr_search.semantic_chunk_search(
                long_text,
                "prescription",
                max_chars=2000,
                chunk_size=200,
                overlap=20,
                top_k=4,
            )

        assert out is not None
        # Output is divided into [~offset N, score X.X]\nchunk blocks.
        # Extract the offset numbers and ensure they're ascending.
        import re
        offsets = [int(m) for m in re.findall(r"\[~offset (\d+),", out)]
        assert offsets == sorted(offsets), f"offsets not sorted: {offsets}"

    def test_cache_size_bounded(self):
        """The chunk cache should evict when capacity is exceeded."""
        fake = _FakeModel()
        original_max = ocr_search._CACHE_MAX

        with patch.object(ocr_search, "_get_model", return_value=fake), \
             patch.object(ocr_search, "_CACHE_MAX", 3):
            for i in range(5):
                # Make each text unique so it doesn't share a hash key.
                txt = f"document {i} " + ("x " * 7000)
                ocr_search.semantic_chunk_search(txt, "x", max_chars=1000)
            # Cache should hold at most _CACHE_MAX = 3 entries.
            assert ocr_search.get_chunk_cache_size() <= 3

        # Sanity: original constant unaffected (just patched within the with).
        assert ocr_search._CACHE_MAX == original_max
