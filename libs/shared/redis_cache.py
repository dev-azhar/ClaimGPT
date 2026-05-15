"""
Redis caching layer for ClaimGPT.

Provides efficient caching of frequently accessed data to reduce database load:
- Workflow states
- Claim statuses
- Job information
- Validation results

Uses Redis as an LRU cache with automatic expiration.
"""

import json
import logging
import os
from typing import Any, Optional, TypeVar, Callable
from functools import wraps
from datetime import datetime, timedelta
import redis
from redis import Redis
from redis.exceptions import RedisError, ConnectionError

logger = logging.getLogger("redis_cache")

T = TypeVar('T')

# Default cache TTLs (in seconds)
DEFAULT_TTL = 300  # 5 minutes
WORKFLOW_STATE_TTL = 60  # 1 minute (frequently updated)
CLAIM_STATUS_TTL = 300  # 5 minutes
JOB_INFO_TTL = 120  # 2 minutes


class RedisCache:
    """Redis cache manager for ClaimGPT."""
    
    _instance: Optional['RedisCache'] = None
    _client: Optional[Redis] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RedisCache, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        
        # Get Redis URL from environment
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        
        try:
            # Try to create a connection pool
            self._client = redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
                health_check_interval=30,
            )
            
            # Test connection
            self._client.ping()
            logger.info(f"✓ Redis connected: {redis_url}")
        except (ConnectionError, RedisError) as e:
            logger.warning(f"⚠  Redis connection failed: {e}. Cache will be disabled.")
            self._client = None
    
    @property
    def client(self) -> Optional[Redis]:
        """Get Redis client, reconnect if needed."""
        if self._client is None:
            try:
                redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                self._client = redis.from_url(
                    redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=5,
                )
                self._client.ping()
                logger.info("✓ Redis reconnected")
            except Exception as e:
                logger.debug(f"Redis reconnection failed: {e}")
                return None
        return self._client
    
    def is_connected(self) -> bool:
        """Check if Redis is connected."""
        try:
            if self.client:
                self.client.ping()
                return True
        except Exception:
            self._client = None
        return False
    
    def set_json(self, key: str, value: Any, ttl: int = DEFAULT_TTL) -> bool:
        """Set a JSON value in cache."""
        if not self.is_connected():
            return False
        
        try:
            json_str = json.dumps(value)
            self.client.setex(key, ttl, json_str)
            logger.debug(f"[Cache] SET {key} (TTL: {ttl}s)")
            return True
        except Exception as e:
            logger.warning(f"[Cache] Failed to set {key}: {e}")
            return False
    
    def get_json(self, key: str) -> Optional[Any]:
        """Get a JSON value from cache."""
        if not self.is_connected():
            return None
        
        try:
            value = self.client.get(key)
            if value:
                logger.debug(f"[Cache] HIT {key}")
                return json.loads(value)
            logger.debug(f"[Cache] MISS {key}")
            return None
        except Exception as e:
            logger.warning(f"[Cache] Failed to get {key}: {e}")
            return None
    
    def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        if not self.is_connected():
            return False
        
        try:
            self.client.delete(key)
            logger.debug(f"[Cache] DELETE {key}")
            return True
        except Exception as e:
            logger.warning(f"[Cache] Failed to delete {key}: {e}")
            return False
    
    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern."""
        if not self.is_connected():
            return 0
        
        try:
            keys = self.client.keys(pattern)
            if keys:
                deleted = self.client.delete(*keys)
                logger.debug(f"[Cache] DELETE PATTERN {pattern} ({deleted} keys)")
                return deleted
            return 0
        except Exception as e:
            logger.warning(f"[Cache] Failed to delete pattern {pattern}: {e}")
            return 0
    
    def get_or_fetch(self, key: str, fetch_func: Callable[[], Any], ttl: int = DEFAULT_TTL) -> Any:
        """Get from cache or fetch from function if miss."""
        # Try cache first
        cached = self.get_json(key)
        if cached is not None:
            return cached
        
        # Cache miss - fetch from function
        try:
            value = fetch_func()
            if value is not None:
                self.set_json(key, value, ttl)
            return value
        except Exception as e:
            logger.error(f"[Cache] Fetch function failed for {key}: {e}")
            return None
    
    def invalidate_claim_cache(self, claim_id: str) -> None:
        """Invalidate all cache entries for a claim."""
        patterns = [
            f"claim:{claim_id}:*",
            f"workflow:{claim_id}:*",
            f"job:{claim_id}:*",
        ]
        total_deleted = 0
        for pattern in patterns:
            total_deleted += self.delete_pattern(pattern)
        logger.info(f"[Cache] Invalidated {total_deleted} entries for claim {claim_id}")
    
    def flush_all(self) -> bool:
        """Flush all cache (use with caution)."""
        if not self.is_connected():
            return False
        
        try:
            self.client.flushdb()
            logger.warning("[Cache] FLUSHED all cache")
            return True
        except Exception as e:
            logger.warning(f"[Cache] Failed to flush: {e}")
            return False


def cached(ttl: int = DEFAULT_TTL, key_prefix: str = ""):
    """
    Decorator to cache function results.
    
    Args:
        ttl: Time to live in seconds
        key_prefix: Prefix for cache key (if not provided, uses function name)
    
    Example:
        @cached(ttl=300, key_prefix="workflow")
        def get_workflow_state(claim_id):
            ...
    """
    def decorator(func: Callable) -> Callable:
        prefix = key_prefix or func.__name__
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Build cache key from function name and arguments
            cache_key = f"{prefix}:{':'.join(str(a) for a in args)}"
            if kwargs:
                cache_key += f":{':'.join(f'{k}={v}' for k, v in kwargs.items())}"
            
            cache = RedisCache()
            
            # Try to get from cache
            cached_value = cache.get_json(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Cache miss - call function
            result = func(*args, **kwargs)
            
            # Store in cache
            if result is not None:
                cache.set_json(cache_key, result, ttl)
            
            return result
        
        return wrapper
    
    return decorator


# Singleton instance
_cache_instance = RedisCache()


def get_cache() -> RedisCache:
    """Get the Redis cache singleton."""
    return _cache_instance


# Cache key builders
def workflow_state_key(claim_id: str, current_step: str = None) -> str:
    """Build cache key for workflow state."""
    if current_step:
        return f"workflow:{claim_id}:{current_step}"
    return f"workflow:{claim_id}:current"


def claim_status_key(claim_id: str) -> str:
    """Build cache key for claim status."""
    return f"claim:{claim_id}:status"


def job_info_key(job_id: str) -> str:
    """Build cache key for job information."""
    return f"job:{job_id}:info"


def ocr_job_key(claim_id: str) -> str:
    """Build cache key for OCR job."""
    return f"job:{claim_id}:ocr"


def parse_job_key(claim_id: str) -> str:
    """Build cache key for parse job."""
    return f"job:{claim_id}:parse"


# Batch cache operations
class CacheBatch:
    """Batch cache operations for efficiency."""
    
    def __init__(self):
        self.cache = get_cache()
        self.operations = []
    
    def set(self, key: str, value: Any, ttl: int = DEFAULT_TTL):
        """Queue a set operation."""
        self.operations.append(('set', key, value, ttl))
        return self
    
    def delete(self, key: str):
        """Queue a delete operation."""
        self.operations.append(('delete', key))
        return self
    
    def execute(self) -> int:
        """Execute all queued operations."""
        count = 0
        for op in self.operations:
            if op[0] == 'set':
                _, key, value, ttl = op
                if self.cache.set_json(key, value, ttl):
                    count += 1
            elif op[0] == 'delete':
                _, key = op
                if self.cache.delete(key):
                    count += 1
        return count
