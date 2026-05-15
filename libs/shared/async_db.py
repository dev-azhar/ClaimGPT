"""
Async database utilities for ClaimGPT.

Provides async session management for use in Celery tasks and FastAPI endpoints.
"""

import sys
import os
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy import text

# Ensure the project root is in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)


async def get_async_engine(database_url: str = None):
    """Create and return an async engine."""
    if database_url is None:
        from libs.shared.config import settings
        database_url = settings.database_url
    
    # Convert psycopg2 URL to asyncpg URL if needed
    if "postgresql://" in database_url:
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif "postgres://" in database_url:
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://")
    
    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=300,
        echo=False,
    )
    return engine


async def get_async_session_factory(database_url: str = None):
    """Create and return an async session factory."""
    engine = await get_async_engine(database_url)
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


@asynccontextmanager
async def get_async_session(database_url: str = None):
    """
    Context manager for async database sessions.
    
    Usage:
        async with get_async_session() as session:
            result = await session.execute(select(Claim).filter(...))
    """
    session = None
    try:
        factory = await get_async_session_factory(database_url)
        session = factory()
        yield session
    except Exception:
        if session is not None:
            await session.rollback()
        raise
    finally:
        if session is not None:
            await session.close()


async def check_async_db_health(database_url: str = None) -> bool:
    """Check if the async database is reachable."""
    try:
        async with get_async_session(database_url) as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# Convenience function for creating a session outside of context manager
# (useful for Celery tasks that need to pass session around)
async def create_async_session(database_url: str = None) -> AsyncSession:
    """
    Create a new async session.
    
    WARNING: You must call await session.close() manually when done.
    Prefer using get_async_session() context manager instead.
    """
    factory = await get_async_session_factory(database_url)
    return factory()
