"""
Pytest configuration and shared fixtures for the Query Refinement Module tests.
"""
import os
import logging
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from query_refinement_module.db.database import Base

# Ensure logging internals do not raise during late interpreter/test teardown.
# Some third-party cleanup hooks emit logs after pytest capture streams close.
logging.raiseExceptions = False
logging.getLogger("asyncio").setLevel(logging.WARNING)


@pytest.fixture(scope="session", autouse=True)
def configure_test_logging():
    """Stabilize logging during pytest teardown.

    Some third-party libraries (e.g., litellm cleanup hooks) may emit late asyncio
    debug logs while pytest is closing capture streams, which can surface as
    ValueError("I/O operation on closed file") from logging internals.
    """
    yield


@pytest.fixture(scope="session")
def test_database_url():
    """Database URL for testing (in-memory SQLite)."""
    # Use a single in-memory database shared across threads via StaticPool.
    # This is required for FastAPI TestClient, which runs requests in a different thread.
    return "sqlite://"


@pytest.fixture(scope="function")
def test_db_engine(test_database_url):
    """Create a fresh database engine for each test."""
    # Add check_same_thread=False for SQLite to work with FastAPI TestClient's threading
    engine = create_engine(
        test_database_url,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def test_db_session(test_db_engine):
    """Create a fresh database session for each test."""
    TestSessionLocal = sessionmaker(bind=test_db_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session")
def api_base_url():
    """Base URL for API tests (versioned)."""
    return os.getenv("TEST_API_URL", "http://localhost:8000/api/v1")


@pytest.fixture(autouse=True)
def reset_test_env():
    """Reset environment variables for each test."""
    original_env = os.environ.copy()
    yield
    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)
