"""
Vector search engine using sentence-transformers + FAISS.

Embeds claim text (OCR + parsed fields) and supports semantic similarity search.
Index is persisted to disk and rebuilt on demand.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import UUID

import numpy as np

from .config import settings

logger = logging.getLogger("search.vector")

# Lazy-loaded globals
_model = None
_index = None
_id_map: List[str] = []  # position → claim_id string
_DIMENSION = 384  # all-MiniLM-L6-v2 output dimension


def _get_model():
    """Lazy-load the sentence-transformer model."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(settings.embedding_model)
            logger.info("Loaded embedding model: %s", settings.embedding_model)
        except ImportError:
            logger.warning("sentence-transformers not installed — vector search unavailable")
            return None
    return _model


def _get_index():
    """Lazy-load or create the FAISS index."""
    global _index, _id_map
    if _index is not None:
        return _index

    try:
        import faiss
    except ImportError:
        logger.warning("faiss-cpu not installed — vector search unavailable")
        return None

    index_path = Path(settings.faiss_index_path)
    id_map_path = Path(settings.faiss_id_map_path)

    if index_path.exists() and id_map_path.exists():
        _index = faiss.read_index(str(index_path))
        with open(id_map_path) as f:
            _id_map = json.load(f)
        logger.info("Loaded FAISS index: %d vectors", _index.ntotal)
    else:
        _index = faiss.IndexFlatIP(_DIMENSION)  # inner product (cosine after L2-norm)
        _id_map = []
        logger.info("Created empty FAISS index")

    return _index


def _save_index() -> None:
    """Persist FAISS index and ID map to disk."""
    if _index is None:
        return
    try:
        import faiss
        faiss.write_index(_index, str(settings.faiss_index_path))
        with open(settings.faiss_id_map_path, "w") as f:
            json.dump(_id_map, f)
        logger.info("Saved FAISS index: %d vectors", _index.ntotal)
    except Exception:
        logger.exception("Failed to save FAISS index")


def embed_text(text: str) -> Optional[np.ndarray]:
    """Encode text to a normalized embedding vector."""
    model = _get_model()
    if model is None:
        return None
    vec = model.encode([text], normalize_embeddings=True)
    return vec[0]


def index_claim(claim_id: str, text: str) -> bool:
    """Add or update a claim's embedding in the FAISS index."""
    index = _get_index()
    model = _get_model()
    if index is None or model is None:
        return False

    vec = model.encode([text], normalize_embeddings=True).astype(np.float32)

    # Remove old entry if exists
    if claim_id in _id_map:
        _rebuild_without(claim_id)

    index.add(vec)
    _id_map.append(claim_id)
    _save_index()
    return True


def index_claims_batch(items: List[Tuple[str, str]]) -> int:
    """Batch-index multiple (claim_id, text) pairs."""
    index = _get_index()
    model = _get_model()
    if index is None or model is None:
        return 0

    texts = [text for _, text in items]
    ids = [cid for cid, _ in items]

    # Remove existing entries
    existing = set(_id_map)
    to_remove = [cid for cid in ids if cid in existing]
    if to_remove:
        for cid in to_remove:
            _rebuild_without(cid)

    vecs = model.encode(texts, normalize_embeddings=True, batch_size=32).astype(np.float32)
    index.add(vecs)
    _id_map.extend(ids)
    _save_index()
    return len(ids)


def search_similar(query_text: str, top_k: int = 10) -> List[Tuple[str, float]]:
    """
    Search for claims most similar to query_text.
    Returns list of (claim_id, score) tuples sorted by relevance.
    """
    index = _get_index()
    if index is None or index.ntotal == 0:
        return []

    query_vec = embed_text(query_text)
    if query_vec is None:
        return []

    query_vec = query_vec.reshape(1, -1).astype(np.float32)
    k = min(top_k, index.ntotal)

    scores, indices = index.search(query_vec, k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or idx >= len(_id_map):
            continue
        results.append((_id_map[idx], float(score)))

    return results


def _rebuild_without(claim_id: str) -> None:
    """Rebuild index excluding a specific claim_id (for upsert support)."""
    global _index, _id_map

    try:
        import faiss
    except ImportError:
        return

    if _index is None or _index.ntotal == 0:
        return

    # Extract all vectors
    n = _index.ntotal
    all_vecs = np.zeros((n, _DIMENSION), dtype=np.float32)
    for i in range(n):
        all_vecs[i] = _index.reconstruct(i)

    # Filter out target claim
    keep_indices = [i for i, cid in enumerate(_id_map) if cid != claim_id]
    if len(keep_indices) == n:
        return  # not found

    new_vecs = all_vecs[keep_indices]
    new_ids = [_id_map[i] for i in keep_indices]

    _index = faiss.IndexFlatIP(_DIMENSION)
    if len(new_vecs) > 0:
        _index.add(new_vecs)
    _id_map = new_ids


def get_index_stats() -> Dict:
    """Return index statistics."""
    index = _get_index()
    return {
        "total_vectors": index.ntotal if index else 0,
        "dimension": _DIMENSION,
        "model": settings.embedding_model,
    }
