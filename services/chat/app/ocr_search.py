"""Semantic chunk search over OCR text for chat context retrieval.

Replaces the keyword-scoring approach in ``main.py::_search_ocr_for_query``
with embedding-based similarity. Chunks are embedded once per
``(text_hash, chunk_size, overlap)`` and cached so subsequent queries
on the same document are sub-millisecond.

This is the *document-side* counterpart to the *catalog-side* RAG in
``services.coding.app.icd10_rag``. Both reuse the same MiniLM model
loaded by the coding service.

Public API
----------
- ``semantic_chunk_search(full_text, query, max_chars=12000)`` — returns
  the most relevant slice of ``full_text`` for ``query``, or ``None`` if
  the embedding model is unavailable so the caller can fall back to
  keyword scoring.
- ``clear_chunk_cache()`` — invalidate the per-document chunk cache.
"""
from __future__ import annotations

import hashlib
import logging
import os
from collections import OrderedDict
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

logger = logging.getLogger("chat.ocr_search")

# ── Tunables (env-overridable) ────────────────────────────────────
_CHUNK_SIZE = int(os.environ.get("CHAT_OCR_CHUNK_SIZE", "500"))       # chars
_CHUNK_OVERLAP = int(os.environ.get("CHAT_OCR_CHUNK_OVERLAP", "100"))  # chars
_TOP_K = int(os.environ.get("CHAT_OCR_TOP_K", "8"))
_CACHE_MAX = int(os.environ.get("CHAT_OCR_CACHE_MAX", "32"))


# ── Per-document chunk-embedding cache ────────────────────────────
# Keyed on (text_hash, chunk_size, overlap). FIFO/LRU-style eviction
# via OrderedDict. Bounded so we don't leak memory on long-lived
# processes that see many distinct claims.

_chunk_cache: "OrderedDict[str, tuple[list[tuple[int, str]], NDArray[np.float32]]]" = OrderedDict()


def _hash_text(text: str) -> str:
    """Stable 16-char SHA1 prefix for cache keying."""
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _chunks(text: str, size: int, overlap: int) -> list[tuple[int, str]]:
    """Split ``text`` into overlapping chunks.

    Returns a list of ``(offset, chunk_text)`` tuples preserving original
    positions so the caller can reorder selected chunks back into reading
    order.
    """
    if not text:
        return []
    out: list[tuple[int, str]] = []
    step = max(1, size - overlap)
    i = 0
    while i < len(text):
        chunk = text[i : i + size].strip()
        if chunk:
            out.append((i, chunk))
        i += step
    return out


def _get_model():
    """Lazy-import the shared MiniLM model from the coding service."""
    try:
        from services.coding.app.icd10_rag import _load_model
        return _load_model()
    except Exception:
        logger.warning("Embedding model unavailable for OCR semantic search", exc_info=True)
        return None


def _embed_chunks(
    text: str, chunk_size: int, overlap: int,
) -> tuple[list[tuple[int, str]] | None, "NDArray[np.float32] | None"]:
    """Return (chunks, embeddings) for ``text``, embedding only on cache miss."""
    key = f"{_hash_text(text)}:{chunk_size}:{overlap}"
    if key in _chunk_cache:
        _chunk_cache.move_to_end(key)
        return _chunk_cache[key]

    chunks = _chunks(text, chunk_size, overlap)
    if not chunks:
        return [], np.zeros((0, 1), dtype=np.float32)

    model = _get_model()
    if model is None:
        return None, None

    vectors = model.encode(
        [c[1] for c in chunks],
        normalize_embeddings=True,
        show_progress_bar=False,
        batch_size=64,
    )
    vectors = np.array(vectors, dtype=np.float32)

    _chunk_cache[key] = (chunks, vectors)
    while len(_chunk_cache) > _CACHE_MAX:
        _chunk_cache.popitem(last=False)

    return chunks, vectors


def semantic_chunk_search(
    full_text: str,
    query: str,
    max_chars: int = 12000,
    top_k: int = _TOP_K,
    chunk_size: int = _CHUNK_SIZE,
    overlap: int = _CHUNK_OVERLAP,
) -> str | None:
    """Return a ``max_chars``-bounded slice of ``full_text`` most relevant to ``query``.

    Returns
    -------
    str
        Concatenated top-``top_k`` chunks (in document order) with brief
        provenance markers, fitting within ``max_chars``.
    None
        If the embedding model is unavailable. Callers should fall back
        to a keyword-scored slice in that case.

    The first call on a given document pays the embedding cost
    (~10-100 ms for typical claims, depending on length); subsequent
    calls hit the chunk cache and are sub-millisecond.
    """
    if not full_text or not query or not query.strip():
        return None

    # Tiny documents: no need to chunk/embed — just return as-is.
    if len(full_text) <= max_chars:
        return full_text

    try:
        chunks, embeddings = _embed_chunks(full_text, chunk_size, overlap)
    except Exception:
        logger.warning("Failed to embed OCR chunks; caller should fall back", exc_info=True)
        return None

    if chunks is None or embeddings is None or len(chunks) == 0:
        return None

    model = _get_model()
    if model is None:
        return None

    q_vec = model.encode([query.strip()], normalize_embeddings=True)
    q_vec = np.array(q_vec, dtype=np.float32)
    # Cosine similarity = dot product since both sides are L2-normalized.
    scores = embeddings @ q_vec[0]

    # Pick top-k by score.
    k = min(top_k, len(scores))
    top = np.argpartition(scores, -k)[-k:]
    top_sorted = top[np.argsort(-scores[top])]

    # Reorder selected chunks back into document order so the LLM sees
    # context flowing naturally rather than highest-scored-first.
    selected = sorted(
        [(int(i), float(scores[i])) for i in top_sorted if scores[i] > 0],
        key=lambda x: chunks[x[0]][0],
    )
    if not selected:
        return None

    out_parts: list[str] = []
    budget = max_chars
    for idx, score in selected:
        offset, text = chunks[idx]
        if budget <= 0:
            break
        piece = text[:budget]
        out_parts.append(f"[~offset {offset}, score {score:.2f}]\n{piece}")
        budget -= len(piece)

    return "\n\n".join(out_parts) if out_parts else None


def clear_chunk_cache() -> None:
    """Drop all cached chunk embeddings (e.g. on test teardown)."""
    _chunk_cache.clear()


def get_chunk_cache_size() -> int:
    """Return the number of cached documents (for monitoring)."""
    return len(_chunk_cache)
