from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings
from libs.shared.db_config import create_optimized_engine, create_session_factory

# Use optimized engine with larger pool for concurrent uploads
engine = create_optimized_engine(
    settings.database_url,
    pool_size=20,        # Increased from default 5
    max_overflow=40,     # Increased from default 10
    pool_recycle=300,
)
SessionLocal = create_session_factory(engine)

from libs.shared.db import Base


def check_db_health() -> bool:
    """Return True if the database is reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
