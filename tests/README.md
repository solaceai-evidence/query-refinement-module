# Test Organization

This directory contains all tests for the Query Refinement Module.

## Structure

```
tests/
├── unit/                    # Unit tests for individual components
│   ├── test_core.py        # Core functionality tests
│   ├── test_analyzers.py   # Analyzer component tests
│   ├── test_providers.py   # Provider tests
│   └── ...
├── integration/             # Integration tests (multiple components)
│   └── test_db_setup.py    # Database setup and CRUD validation
├── api/                     # API endpoint tests
│   ├── test_api_endpoints.py    # Comprehensive API test suite
│   ├── run_api_tests.sh         # Automated clean test runner
│   └── stop_api_server.sh       # Server cleanup script
└── test_examples_validation.py  # Schema examples validation
```

## Running Tests

### Unit Tests
```bash
# Run all unit tests
poetry run pytest tests/unit/

# Run specific test file
poetry run pytest tests/unit/test_core.py

# Run with coverage
poetry run pytest tests/unit/ --cov=query_refinement_module
```

### Integration Tests
```bash
# Run all integration tests
poetry run pytest tests/integration/

# Run database tests
poetry run python tests/integration/test_db_setup.py
```

### API Tests
```bash
# Automated clean test run (recommended)
cd tests/api && ./run_api_tests.sh

# Or run manually
poetry run python tests/api/test_api_endpoints.py

# Stop test server
cd tests/api && ./stop_api_server.sh
```

### All Tests
```bash
# Run all tests except API (which need server running)
poetry run pytest tests/

# Run everything including API tests
poetry run pytest tests/ && cd tests/api && ./run_api_tests.sh
```

## Test Guidelines

### Unit Tests (`tests/unit/`)
- Test individual functions/classes in isolation
- Use mocks for external dependencies
- Fast execution (< 1s per test)
- No database or network calls
- Naming: `test_<component>.py`

### Integration Tests (`tests/integration/`)
- Test multiple components working together
- May use real database (SQLite for tests)
- Test end-to-end workflows
- Naming: `test_<feature>_integration.py`

### API Tests (`tests/api/`)
- Test REST API endpoints
- Require running server
- Test authentication, authorization, CRUD operations
- Use clean database for each run (via `run_api_tests.sh`)
- Naming: `test_api_<feature>.py`

## Writing New Tests

### Unit Test Example
```python
# tests/unit/test_my_component.py
import pytest
from query_refinement_module.my_module import MyClass

def test_my_function():
    result = MyClass().my_function("input")
    assert result == "expected_output"

def test_my_function_error():
    with pytest.raises(ValueError):
        MyClass().my_function(None)
```

### Integration Test Example
```python
# tests/integration/test_my_feature_integration.py
import pytest
from query_refinement_module.db.crud import create_user
from query_refinement_module.db.database import SessionLocal

def test_user_creation_workflow():
    db = SessionLocal()
    try:
        user = create_user(db, "test@example.com", "Test", "password")
        assert user.id is not None
        assert user.email == "test@example.com"
    finally:
        db.close()
```

### API Test Example
```python
# tests/api/test_api_my_feature.py
import requests

BASE_URL = "http://localhost:8000"

def test_my_endpoint():
    response = requests.post(f"{BASE_URL}/api/my-endpoint", json={"data": "value"})
    assert response.status_code == 200
    assert response.json()["result"] == "expected"
```

## Continuous Integration

For CI/CD pipelines:
```bash
# Install dependencies
poetry install

# Run linting
poetry run flake8 query_refinement_module
poetry run mypy query_refinement_module

# Run unit and integration tests
poetry run pytest tests/unit/ tests/integration/ -v --cov=query_refinement_module

# Run API tests (in CI, start server in background first)
poetry run uvicorn query_refinement_module.api.main:app --host 0.0.0.0 --port 8000 &
sleep 5
poetry run python tests/api/test_api_endpoints.py
```

## Test Database

- Unit tests: No database (use mocks)
- Integration tests: Use SQLite in-memory or temporary file
- API tests: Use `query_refinement.db` (cleaned by `run_api_tests.sh`)

For production testing, set `DATABASE_URL` environment variable to use PostgreSQL.
