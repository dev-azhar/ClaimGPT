import hashlib
from typing import List

def calculate_sha256(file_bytes: bytes) -> str:
    """Calculate SHA-256 hash for file bytes."""
    return hashlib.sha256(file_bytes).hexdigest()

def calculate_claim_set_hash(content_hashes: List[str]) -> str:
    """
    Given a list of content_hash values, sort, join, and hash them for set-based idempotency.
    """
    sorted_hashes = sorted(content_hashes)
    joined = ''.join(sorted_hashes)
    return hashlib.sha256(joined.encode('utf-8')).hexdigest()
