"""
Optimized database engine configuration for high-concurrency scenarios.

This module provides pre-configured engine factories with optimized pool settings
for handling 30+ concurrent claim uploads.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool, StaticPool
import logging

logger = logging.getLogger("db_config")


def create_optimized_engine(
    database_url: str,
    pool_size: int = 20,
    max_overflow: int = 40,
    pool_recycle: int = 300,
    pool_pre_ping: bool = True,
    echo: bool = False,
    **kwargs
):
    """
    Create a SQLAlchemy engine with optimized pool settings for high concurrency.
    
    Args:
        database_url: Database connection URL
        pool_size: Number of persistent connections (default 20, increase for high concurrency)
        max_overflow: Maximum connections above pool_size (default 40)
        pool_recycle: Seconds to recycle connections (default 300 = 5 min)
        pool_pre_ping: Verify connections before using (default True)
        echo: Log SQL statements (default False)
    
    Returns:
        SQLAlchemy Engine configured for high concurrency
    """
    
    engine = create_engine(
        database_url,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
        pool_pre_ping=pool_pre_ping,
        echo=echo,
        # Optimize connection behavior
        connect_args={
            "connect_timeout": 10,
            "keepalives": 1,
            "keepalives_idle": 30,
        },
        **kwargs
    )
    
    # Log pool checkout/checkin for debugging
    @event.listens_for(engine, "connect")
    def receive_connect(dbapi_conn, connection_record):
        logger.debug(f"New DB connection established. Pool size: {engine.pool.size()}, Checked-in: {engine.pool.checkedin()}")
    
    @event.listens_for(engine, "checkin")
    def receive_checkin(dbapi_conn, connection_record):
        logger.debug(f"Connection returned to pool. Checked-in: {engine.pool.checkedin()}")
    
    return engine


def create_session_factory(engine, autoflush: bool = False, autocommit: bool = False):
    """
    Create a session factory with optimized settings.
    
    Args:
        engine: SQLAlchemy Engine
        autoflush: Auto-flush settings (default False for explicit control)
        autocommit: Auto-commit settings (default False for explicit control)
    
    Returns:
        sessionmaker instance
    """
    return sessionmaker(
        bind=engine,
        autoflush=autoflush,
        autocommit=autocommit,
        expire_on_commit=False,  # Avoid extra queries after commit
    )
