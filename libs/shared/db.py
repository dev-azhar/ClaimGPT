import sys
import os
# Ensure the project root is in sys.path regardless of how the worker is started
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
if root_dir not in sys.path:
	sys.path.insert(0, root_dir)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from libs.shared.config import settings
from contextvars import ContextVar
from contextlib import contextmanager
import time
import logging

logger = logging.getLogger("shared.db")

# Track db writes locally in memory and globally in Redis for Read-Your-Own-Writes consistency
force_master_var: ContextVar[bool] = ContextVar("force_master", default=False)
_last_write_timestamp = 0.0

@contextmanager
def force_master_session():
    token = force_master_var.set(True)
    try:
        yield
    finally:
        force_master_var.reset(token)

def record_write():
    global _last_write_timestamp
    now = time.time()
    _last_write_timestamp = now
    
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        try:
            import redis
            r = redis.Redis.from_url(redis_url, socket_timeout=1)
            # Set with a 10 second expiration
            r.set("last_db_write_timestamp", str(now), ex=10)
        except Exception as e:
            logger.debug(f"Failed to record write to Redis: {e}")

def is_recent_write(threshold=5.0) -> bool:
    now = time.time()
    # 1. Check local variable first (fast path)
    if (now - _last_write_timestamp) < threshold:
        return True
        
    # 2. Check Redis (coordinated across multiple containers/processes)
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        try:
            import redis
            r = redis.Redis.from_url(redis_url, socket_timeout=1)
            val = r.get("last_db_write_timestamp")
            if val:
                t = float(val.decode("utf-8"))
                if (now - t) < threshold:
                    return True
        except Exception as e:
            logger.debug(f"Failed to check write timestamp from Redis: {e}")
            
    return False

Base = declarative_base()

# Create write and read engines
writer_engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_recycle=300
)

reader_engine = create_engine(
    settings.database_read_url or settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_recycle=300
)

# For backward compatibility, expose the writer_engine as engine
engine = writer_engine

class RoutingSession(Session):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.force_master = False
        self._checked_recent_write = None

    def get_bind(self, mapper=None, clause=None, **kw):
        # Route to writer if forced via contextvar or session attribute
        if force_master_var.get() or getattr(self, "force_master", False):
            return writer_engine

        # Check if we are flushing or writing
        is_write = False
        if self._flushing:
            is_write = True
        elif clause is not None:
            stmt = str(clause).lower().strip()
            if any(stmt.startswith(w) for w in ("insert", "update", "delete", "create", "alter", "drop", "truncate")):
                is_write = True

        if is_write:
            record_write()
            self._checked_recent_write = True  # Force master for subsequent queries in this session
            return writer_engine

        # Route to writer if a write occurred recently in the system
        if self._checked_recent_write is None:
            self._checked_recent_write = is_recent_write(threshold=5.0)

        if self._checked_recent_write:
            return writer_engine

        # Default to replica/reader database
        return reader_engine

SessionLocal = sessionmaker(class_=RoutingSession, autocommit=False, autoflush=False)

# --- Context manager for safe DB session handling ---
from contextlib import contextmanager

@contextmanager
def get_db_session():
	session = None
	try:
		session = SessionLocal()
		yield session
	except Exception:
		if session is not None:
			session.rollback()
		raise
	finally:
		if session is not None:
			session.close()

def check_db_health() -> bool:
    try:
        with writer_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False