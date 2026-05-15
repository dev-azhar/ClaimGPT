"""
Caching utilities for the ingress service.

Provides cached versions of common database queries to reduce load on the main database.
"""

import logging
from typing import Optional
import uuid
from libs.shared.redis_cache import get_cache
from services.ingress.app.models import Claim, Document

logger = logging.getLogger("ingress_cache")

# Cache TTLs
CLAIM_CACHE_TTL = 600  # 10 minutes
DOCUMENT_CACHE_TTL = 600  # 10 minutes
CLAIM_LIST_CACHE_TTL = 300  # 5 minutes


def cache_claim(claim: Claim) -> None:
    """Cache a claim object."""
    cache = get_cache()
    cache_key = f"claim:{claim.id}:data"
    cache_data = {
        "id": str(claim.id),
        "policy_id": claim.policy_id,
        "patient_id": claim.patient_id,
        "status": claim.status,
        "source": claim.source,
        "created_at": claim.created_at.isoformat() if claim.created_at else None,
        "updated_at": claim.updated_at.isoformat() if claim.updated_at else None,
    }
    cache.set_json(cache_key, cache_data, CLAIM_CACHE_TTL)
    logger.debug(f"[Cache] Cached claim {claim.id}")


def get_cached_claim(claim_id: uuid.UUID) -> Optional[dict]:
    """Get a cached claim object."""
    cache = get_cache()
    cache_key = f"claim:{claim_id}:data"
    return cache.get_json(cache_key)


def cache_claim_status(claim_id: uuid.UUID, status: str) -> None:
    """Cache claim status for quick lookups."""
    cache = get_cache()
    cache_key = f"claim:{claim_id}:status"
    cache.set_json(cache_key, {"status": status, "claim_id": str(claim_id)}, CLAIM_CACHE_TTL)
    logger.debug(f"[Cache] Cached claim {claim_id} status: {status}")


def get_cached_claim_status(claim_id: uuid.UUID) -> Optional[str]:
    """Get cached claim status without DB hit."""
    cache = get_cache()
    cache_key = f"claim:{claim_id}:status"
    cached = cache.get_json(cache_key)
    if cached:
        logger.debug(f"[Cache] Claim {claim_id} status HIT: {cached['status']}")
        return cached.get("status")
    return None


def cache_documents(claim_id: uuid.UUID, documents: list) -> None:
    """Cache documents list for a claim."""
    cache = get_cache()
    cache_key = f"claim:{claim_id}:documents"
    docs_data = [
        {
            "id": str(doc.id),
            "file_name": doc.file_name,
            "file_type": doc.file_type,
            "content_hash": doc.content_hash,
            "created_at": doc.created_at.isoformat() if hasattr(doc, 'created_at') and doc.created_at else None,
        }
        for doc in documents
    ]
    cache.set_json(cache_key, {"documents": docs_data, "count": len(docs_data)}, DOCUMENT_CACHE_TTL)
    logger.debug(f"[Cache] Cached {len(documents)} documents for claim {claim_id}")


def get_cached_documents(claim_id: uuid.UUID) -> Optional[list]:
    """Get cached documents for a claim."""
    cache = get_cache()
    cache_key = f"claim:{claim_id}:documents"
    cached = cache.get_json(cache_key)
    if cached:
        logger.debug(f"[Cache] Documents HIT for claim {claim_id}: {cached['count']} docs")
        return cached.get("documents")
    return None


def cache_content_hash_lookup(content_hash: str, claim_id: Optional[uuid.UUID] = None) -> None:
    """Cache content hash to claim mapping for deduplication."""
    if not claim_id:
        return
    
    cache = get_cache()
    cache_key = f"hash:{content_hash}"
    cache.set_json(cache_key, {"claim_id": str(claim_id)}, DOCUMENT_CACHE_TTL * 2)  # 20 min TTL
    logger.debug(f"[Cache] Cached content hash lookup: {content_hash} -> {claim_id}")


def get_cached_claim_by_hash(content_hash: str) -> Optional[uuid.UUID]:
    """Get claim ID from cached content hash lookup."""
    cache = get_cache()
    cache_key = f"hash:{content_hash}"
    cached = cache.get_json(cache_key)
    if cached:
        try:
            claim_id = uuid.UUID(cached["claim_id"])
            logger.debug(f"[Cache] Content hash HIT: {content_hash} -> {claim_id}")
            return claim_id
        except (ValueError, KeyError):
            pass
    return None


def invalidate_claim_caches(claim_id: uuid.UUID) -> None:
    """Invalidate all caches for a claim."""
    cache = get_cache()
    patterns = [
        f"claim:{claim_id}:*",
        f"workflow:{claim_id}:*",
        f"job:{claim_id}:*",
        f"validation:{claim_id}:*",
    ]
    total_deleted = 0
    for pattern in patterns:
        total_deleted += cache.delete_pattern(pattern)
    
    if total_deleted > 0:
        logger.info(f"[Cache] Invalidated {total_deleted} cache entries for claim {claim_id}")


def cache_claim_list(page: int, limit: int, filter_status: Optional[str] = None, data: list = None) -> None:
    """Cache a list of claims."""
    if not data:
        return
    
    cache = get_cache()
    status_key = f":{filter_status}" if filter_status else ""
    cache_key = f"claims:list:p{page}:l{limit}{status_key}"
    cache.set_json(cache_key, {"data": data, "page": page, "limit": limit}, CLAIM_LIST_CACHE_TTL)
    logger.debug(f"[Cache] Cached claims list: page={page}, limit={limit}, filter={filter_status}")


def get_cached_claim_list(page: int, limit: int, filter_status: Optional[str] = None) -> Optional[list]:
    """Get cached claim list."""
    cache = get_cache()
    status_key = f":{filter_status}" if filter_status else ""
    cache_key = f"claims:list:p{page}:l{limit}{status_key}"
    cached = cache.get_json(cache_key)
    if cached:
        logger.debug(f"[Cache] Claims list HIT: page={page}, limit={limit}")
        return cached.get("data")
    return None


def invalidate_claim_list_caches() -> None:
    """Invalidate all claim list caches (call when new claim is created)."""
    cache = get_cache()
    deleted = cache.delete_pattern("claims:list:*")
    if deleted > 0:
        logger.debug(f"[Cache] Invalidated {deleted} claim list caches")
