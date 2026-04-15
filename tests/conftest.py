"""Shared test fixtures — in-memory SQLite DB, FastAPI test clients."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

# In-memory SQLite shared across tests
TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Enable foreign keys for SQLite
@event.listens_for(TEST_ENGINE, "connect")
def _set_sqlite_pragma(dbapi_connection, _):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

TestSession = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)
Base = declarative_base()


@pytest.fixture()
def db():
    """Yield a fresh DB session with tables created/dropped per test."""
    # Import all models so tables exist
    _import_all_models()
    Base.metadata.create_all(bind=TEST_ENGINE)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=TEST_ENGINE)


def _import_all_models():
    """Force model registration — each service declares its own Base,
    so for tests we re-register onto the shared test Base."""
    pass  # Models are imported directly in individual test files


def make_uuid() -> uuid.UUID:
    return uuid.uuid4()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
