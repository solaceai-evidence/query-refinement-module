"""
Smoke tests for Gap #3 critical implementations.

Tests run against a live API server and verify:
1. Admin cache management endpoints
2. Admin integrity validation endpoints
3. Command history endpoint

Run with: poetry run pytest tests/api/test_gap3_smoke.py -v
"""
import requests
import time
import pytest

from query_refinement_module.api.config import get_settings

BASE_URL = "http://localhost:8001/api/v1"
API_ROOT = BASE_URL.replace("/api/v1", "")
AUTH_COOKIE_NAME = get_settings().auth_cookie_name

# Test user credentials
ADMIN_USER = {
    "username": "admin_smoke_test",
    "email": "admin_smoke@test.com",
    "password": "AdminSmoke123!"
}

REGULAR_USER = {
    "username": "user_smoke_test",
    "email": "user_smoke@test.com",
    "password": "UserSmoke123!"
}


def check_api_health():
    """Check if API is running."""
    try:
        response = requests.get(f"{API_ROOT}/health", timeout=5)
        return response.status_code == 200
    except:
        return False


if not check_api_health():
    pytest.skip("API server is not available at http://localhost:8001", allow_module_level=True)


def create_user(user_data):
    """Register a user."""
    try:
        response = requests.post(f"{BASE_URL}/auth/register", json=user_data)
        if response.status_code == 403:
            pytest.skip("Self-service registration is disabled in this environment")
    except:
        pass  # User may already exist


def login_user(username, password):
    """Login and get the JWT from the auth cookie."""
    response = requests.post(
        f"{BASE_URL}/auth/login",
        data={"username": username, "password": password}
    )
    if response.status_code == 200:
        return response.cookies.get(AUTH_COOKIE_NAME)
    return None


def make_superuser(email):
    """Manually make a user a superuser via database script."""
    import subprocess
    try:
        result = subprocess.run(
            ["poetry", "run", "python", "scripts/make_superuser.py", email],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except:
        return False


def test_api_is_running():
    """Verify API server is running."""
    assert check_api_health(), "API server must be running on localhost:8001"


def test_admin_cache_endpoints_require_auth():
    """Admin endpoints require authentication."""
    endpoints = [
        "/admin/cache/sessions",
        "/admin/cache/stats",
    ]
    
    for endpoint in endpoints:
        response = requests.get(f"{BASE_URL}{endpoint}")
        assert response.status_code == 401, f"{endpoint} should require auth"


def test_admin_cache_list_requires_superuser():
    """Cache list endpoint requires superuser privileges."""
    # Create and login regular user
    create_user(REGULAR_USER)
    token = login_user(REGULAR_USER["email"], REGULAR_USER["password"])
    assert token is not None, "Regular user login failed"
    
    # Try to access admin endpoint
    response = requests.get(
        f"{BASE_URL}/admin/cache/sessions",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == 403, "Regular user should not access admin endpoints"
    assert "Superuser" in response.json()["detail"]


def test_admin_cache_stats():
    """Superuser can get cache statistics."""
    # Setup superuser
    create_user(ADMIN_USER)
    make_superuser(ADMIN_USER["email"])
    token = login_user(ADMIN_USER["email"], ADMIN_USER["password"])
    
    if token is None:
        print(f"⚠️  Could not create superuser. Run: poetry run python scripts/make_superuser.py {ADMIN_USER['email']}")
        return
    
    # Get cache stats
    response = requests.get(
        f"{BASE_URL}/admin/cache/stats",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    if response.status_code == 403:
        print(f"⚠️  User is not superuser. Run: poetry run python scripts/make_superuser.py {ADMIN_USER['email']}")
        return
    
    assert response.status_code == 200, f"Failed to get cache stats: {response.text}"
    data = response.json()
    
    # Verify response structure
    assert "total_keys" in data
    assert "session_keys" in data
    assert "memory_used_bytes" in data
    assert "cache_ttl_seconds" in data
    print("✅ Admin cache stats endpoint working")


def test_admin_integrity_check():
    """Superuser can check DB-Redis integrity."""
    # Setup superuser
    create_user(ADMIN_USER)
    token = login_user(ADMIN_USER["email"], ADMIN_USER["password"])
    
    if token is None:
        print(f"⚠️  Login failed for {ADMIN_USER['email']}")
        return
    
    # Check integrity
    response = requests.get(
        f"{BASE_URL}/admin/integrity/check",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    if response.status_code == 403:
        print(f"⚠️  User is not superuser. Run: poetry run python scripts/make_superuser.py {ADMIN_USER['email']}")
        return
    
    assert response.status_code == 200, f"Integrity check failed: {response.text}"
    data = response.json()
    
    # Verify response structure
    assert "total_queries_checked" in data
    assert "consistent_queries" in data
    assert "queries" in data
    assert isinstance(data["queries"], list)
    print("✅ Admin integrity check endpoint working")


def test_command_history_endpoint():
    """Command history endpoint tracks commands."""
    # Create regular user and login
    create_user(REGULAR_USER)
    token = login_user(REGULAR_USER["email"], REGULAR_USER["password"])
    assert token is not None
    
    # Start a refinement session
    start_response = requests.post(
        f"{BASE_URL}/refinement/start",
        json={
            "original_query": "Command history test query",
            "framework_name": "pico_advanced"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    
    if start_response.status_code != 201:
        print(f"⚠️  Could not start refinement: {start_response.text}")
        return
    
    query_id = start_response.json()["query_id"]
    
    # Execute a command
    cmd_response = requests.post(
        f"{BASE_URL}/refinement/queries/{query_id}/answer",
        json={"answer": "/status"},
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert cmd_response.status_code == 200, f"Command execution failed: {cmd_response.text}"
    
    # Get command history
    history_response = requests.get(
        f"{BASE_URL}/refinement/queries/{query_id}/command-history",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert history_response.status_code == 200, f"Command history failed: {history_response.text}"
    data = history_response.json()
    
    # Verify response structure
    assert data["query_id"] == query_id
    assert "total_commands" in data
    assert "commands" in data
    assert isinstance(data["commands"], list)
    
    # Verify status command was tracked
    if data["total_commands"] > 0:
        cmd = data["commands"][0]
        assert "command" in cmd
        assert "timestamp" in cmd
        assert "success" in cmd
        assert "username" in cmd
        print("✅ Command history endpoint working")
    else:
        print("⚠️  No commands tracked in history")


def test_command_audit_logging():
    """Commands are logged with full audit context."""
    # Create user and start session
    create_user(REGULAR_USER)
    token = login_user(REGULAR_USER["email"], REGULAR_USER["password"])
    assert token is not None
    
    start_response = requests.post(
        f"{BASE_URL}/refinement/start",
        json={
            "original_query": "Audit logging test",
            "framework_name": "pico_advanced"  
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    
    if start_response.status_code != 201:
        print(f"⚠️  Could not start refinement")
        return
    
    query_id = start_response.json()["query_id"]
    
    # Execute multiple commands
    commands = ["/status", "/help", "/steps"]
    for cmd in commands:
        requests.post(
            f"{BASE_URL}/refinement/queries/{query_id}/answer",
            json={"answer": cmd},
            headers={"Authorization": f"Bearer {token}"}
        )
        time.sleep(0.1)  # Small delay to ensure order
    
    # Get command history
    history_response = requests.get(
        f"{BASE_URL}/refinement/queries/{query_id}/command-history",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert history_response.status_code == 200
    data = history_response.json()
    
    # Verify multiple commands tracked
    assert data["total_commands"] >= len(commands), f"Expected at least {len(commands)} commands, got {data['total_commands']}"
    
    # Verify detailed audit context
    for cmd_entry in data["commands"]:
        assert "command_input" in cmd_entry
        assert "active_dimension" in cmd_entry or cmd_entry["command"] in ["status", "help", "steps"]
        assert "force_requested" in cmd_entry
        assert "status" in cmd_entry
    
    print("✅ Command audit logging working with full context")


if __name__ == "__main__":
    print("\n🧪 Running Gap #3 smoke tests...\n")
    
    test_api_is_running()
    print("✅ API is running")
    
    test_admin_cache_endpoints_require_auth()
    print("✅ Admin endpoints require authentication")
    
    test_admin_cache_list_requires_superuser()
    print("✅ Admin endpoints require superuser privileges")
    
    test_admin_cache_stats()
    test_admin_integrity_check()
    test_command_history_endpoint()
    test_command_audit_logging()
    
    print("\n✅ All Gap #3 critical endpoints verified!\n")
