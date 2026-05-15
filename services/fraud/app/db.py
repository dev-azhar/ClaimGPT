from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .config import settings
from libs.shared.db_config import create_optimized_engine, create_session_factory

# Use optimized engine with larger pool for concurrent processing
engine = create_optimized_engine(
    settings.database_url,
    pool_size=20,        # Increased from default 5
    max_overflow=40,     # Increased from default 10
    pool_recycle=300,
)
SessionLocal = create_session_factory(engine)

from libs.shared.db import Base  # noqa: E402,F401  (re-export for migrations)


def check_db_health() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
