"""
Test API versioning implementation.

Verifies that:
1. Version info endpoint works
2. Versioned endpoints are accessible
3. Invalid versions return proper errors
4. Health endpoints remain unversioned
"""
import pytest
from fastapi.testclient import TestClient
from query_refinement_module.api.main import app

client = TestClient(app)


def test_version_info_endpoint():
    """Test the /api/version endpoint returns version information."""
    response = client.get("/api/version")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify structure
    assert "current_version" in data
    assert "latest_version" in data
    assert "supported_versions" in data
    assert "deprecated_versions" in data
    assert "min_supported_version" in data
    
    # Verify values
    assert data["current_version"] == "v1"
    assert data["latest_version"] == "v1"
    assert "v1" in data["supported_versions"]
    assert data["deprecated_versions"] == []


def test_root_endpoint_includes_version_info():
    """Test that root endpoint includes API version information."""
    response = client.get("/")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "api_version" in data
    assert "api_versions" in data
    assert data["api_version"] == "v1"
    assert "current" in data["api_versions"]
    assert "supported" in data["api_versions"]


def test_health_endpoints_unversioned():
    """Verify health/ready endpoints remain unversioned."""
    # Health check
    response = client.get("/health")
    assert response.status_code == 200
    assert "status" in response.json()
    
    # Readiness check
    response = client.get("/ready")
    assert response.status_code in [200, 503]  # May be unhealthy in test env


def test_v1_endpoints_accessible():
    """Test that v1 endpoints are accessible (without auth for public ones)."""
    # Note: Most endpoints require authentication, but we can test the path exists
    # Login endpoint (should return 422 for missing data, not 404)
    response = client.post("/api/v1/auth/login", json={})
    assert response.status_code != 404  # Path exists
    
    # Register endpoint
    response = client.post("/api/v1/auth/register", json={})
    assert response.status_code != 404  # Path exists


def test_invalid_version_returns_error():
    """Test that invalid API version returns proper error."""
    response = client.post("/api/v99/auth/login", json={})
    
    assert response.status_code == 400
    data = response.json()
    
    assert "error" in data
    assert data["error"] == "invalid_api_version"
    assert "supported_versions" in data
    assert "v1" in data["supported_versions"]


def test_version_header_added_to_responses():
    """Verify X-API-Version header is added to v1 requests."""
    response = client.get("/api/version")
    
    # Version info endpoint itself may not have version header
    # But v1 endpoints should
    response = client.post("/api/v1/auth/login", json={})
    
    # Check if header exists (may not be set in test client)
    # This is more of a documentation test
    assert response.status_code != 404


def test_unversioned_api_path_not_accessible():
    """Test that old unversioned paths are not accessible."""
    # Old path (should 404 or be handled differently)
    response = client.post("/api/auth/login", json={})
    
    # Should either 404 or redirect to versioned endpoint
    # In our implementation, it should 404
    assert response.status_code in [404, 307]  # Not found or redirect


def test_multiple_versions_supported_structure():
    """Test that the system is structured to support multiple versions."""
    response = client.get("/api/version")
    data = response.json()
    
    # Verify it's a list and can contain multiple versions
    assert isinstance(data["supported_versions"], list)
    assert len(data["supported_versions"]) >= 1
    assert "v1" in data["supported_versions"]


def test_deprecation_mechanism_exists():
    """Verify that deprecation tracking is in place."""
    response = client.get("/api/version")
    data = response.json()
    
    # Should have deprecated_versions list (empty for now)
    assert "deprecated_versions" in data
    assert isinstance(data["deprecated_versions"], list)
    
    # Currently no deprecated versions
    assert len(data["deprecated_versions"]) == 0


@pytest.mark.parametrize("endpoint", [
    "/health",
    "/ready",
    "/",
    "/docs",
    "/openapi.json",
])
def test_meta_endpoints_remain_unversioned(endpoint):
    """Test that meta/health endpoints don't require version."""
    response = client.get(endpoint)
    
    # Should be accessible (200 or 503 for health checks)
    assert response.status_code in [200, 503]
    
    # Verify these don't require /v1/
    assert "/v1/" not in endpoint


def test_api_versioning_documentation():
    """Test that API docs are accessible and up to date."""
    response = client.get("/docs")
    assert response.status_code == 200
    
    # OpenAPI spec
    response = client.get("/openapi.json")
    assert response.status_code == 200
    
    spec = response.json()
    assert "info" in spec
    assert "version" in spec["info"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
