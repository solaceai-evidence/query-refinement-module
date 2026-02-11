"""
Pytest configuration and shared fixtures for the Query Refinement Module tests.
"""
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from query_refinement_module.db.database import Base


@pytest.fixture(scope="session")
def test_database_url():
    """Database URL for testing (in-memory SQLite)."""
    return "sqlite:///:memory:"


@pytest.fixture(scope="function")
def test_db_engine(test_database_url):
    """Create a fresh database engine for each test."""
    # Add check_same_thread=False for SQLite to work with FastAPI TestClient's threading
    engine = create_engine(
        test_database_url, 
        echo=False,
        connect_args={"check_same_thread": False}
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
