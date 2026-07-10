"""
Integration test to verify migration from unversioned to versioned API.

Tests both old and new paths to ensure migration is complete.
"""
import pytest
from fastapi.testclient import TestClient
from query_refinement_module.api.main import app

client = TestClient(app)


class TestVersionedMigration:
    """Test suite for API versioning migration."""
    
    def test_old_unversioned_paths_not_working(self):
        """Verify old unversioned API paths are no longer accessible."""
        old_paths = [
            "/api/auth/login",
            "/api/auth/register",
            "/api/refinement/start",
            "/api/queries/sessions",
            "/api/feedback",
        ]
        
        for path in old_paths:
            response = client.post(path, json={})
            # Should 404 since these paths no longer exist
            assert response.status_code == 404, f"Old path {path} should not be accessible"
    
    def test_new_versioned_paths_working(self):
        """Verify new versioned API paths are accessible."""
        new_paths = [
            "/api/v1/auth/login",
            "/api/v1/auth/register",
            "/api/v1/refinement/start",
            "/api/v1/queries/sessions",
            "/api/v1/feedback",
        ]
        
        for path in new_paths:
            response = client.post(path, json={})
            # Should not 404 (will get 422 for validation or 401 for auth)
            assert response.status_code != 404, f"New path {path} should be accessible"
    
    def test_health_endpoints_unchanged(self):
        """Verify health/meta endpoints remain unversioned."""
        health_paths = [
            "/health",
            "/ready",
            "/",
        ]
        
        for path in health_paths:
            response = client.get(path)
            assert response.status_code in [200, 503], f"Health endpoint {path} should work"
    
    def test_version_info_accessible(self):
        """Verify version info endpoint works."""
        response = client.get("/api/version")
        assert response.status_code == 200
        
        data = response.json()
        assert data["current_version"] == "v1"
        assert "v1" in data["supported_versions"]
    
    def test_client_can_use_new_paths(self):
        """Simulate a client using the versioned API paths."""
        # Simulate login attempt
        response = client.post("/api/v1/auth/login", data={
            "username": "testuser",
            "password": "testpass"
        })
        
        # Will fail authentication but path should exist
        assert response.status_code in [401, 422], "Login endpoint should be accessible"
    
    def test_invalid_version_handled_gracefully(self):
        """Test that invalid versions return helpful errors."""
        response = client.post("/api/v999/auth/login", json={})
        
        assert response.status_code == 400
        data = response.json()
        
        assert "error" in data
        assert "supported_versions" in data
        assert "help" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
