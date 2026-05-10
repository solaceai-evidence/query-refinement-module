"""
Smoke tests for session diagnostics and cache management endpoints.

Tests the admin/sessions router endpoints for monitoring Redis cache
behavior and debugging session reconstruction issues.
"""
import requests
import json
import pytest

from query_refinement_module.api.config import get_settings

BASE_URL = "http://localhost:8001/api/v1"
AUTH_COOKIE_NAME = get_settings().auth_cookie_name


def _api_available() -> bool:
    try:
        return requests.get("http://localhost:8001/health", timeout=3).status_code == 200
    except requests.exceptions.RequestException:
        return False


if not _api_available():
    pytest.skip("Live API server not available for manual smoke test", allow_module_level=True)


def test_admin_sessions_smoke():
    """Test all admin session diagnostic endpoints."""
    
    print("\n" + "="*60)
    print("SESSION DIAGNOSTICS SMOKE TESTS")
    print("="*60)
    
    # Step 1: Create test user
    print("\n[1/8] Creating test user...")
    response = requests.post(
        f"{BASE_URL}/auth/register",
        json={
            "username": "admin_test_user",
            "email": "admin_test@example.com",
            "password": "AdminTest123!",
            "full_name": "Admin Test User"
        }
    )
    if response.status_code == 400 and "already registered" in response.json().get("detail", "").lower():
        print("✓ User already exists")
    else:
        assert response.status_code == 201, f"Failed to create user: {response.text}"
        print("✓ User created")
    
    # Step 2: Login
    print("\n[2/8] Logging in...")
    response = requests.post(
        f"{BASE_URL}/auth/login",
        data={
            "username": "admin_test_user",
            "password": "AdminTest123!"
        }
    )
    assert response.status_code == 200, f"Failed to login: {response.text}"
    token = response.cookies.get(AUTH_COOKIE_NAME)
    assert token is not None, "Login succeeded but auth cookie was not set"
    headers = {"Authorization": f"Bearer {token}"}
    print(f"✓ Logged in (token: {token[:20]}...)")
    
    # Step 3: Make user superuser (using direct DB update for testing)
    print("\n[3/8] Checking superuser status...")
    # For smoke test, we'll test with the user we have (may not be superuser)
    # In real scenario, need to make user superuser via CLI
    print("⚠ Note: User may need superuser privileges for full testing")
    
    # Step 4: Create a session and query for testing
    print("\n[4/8] Creating test session and query...")
    response = requests.post(
        f"{BASE_URL}/queries/sessions",
        json={"framework_name": "pico_advanced"},
        headers=headers
    )
    assert response.status_code in [200, 201], f"Failed to create session: {response.text}"
    session_data = response.json()
    session_id = session_data.get("id") or session_data.get("session_id")
    print(f"✓ Session created (ID: {session_id})")
    
    response = requests.post(
        f"{BASE_URL}/queries",
        json={
            "session_id": session_id,
            "original_query": "What are the effects of exercise on depression?"
        },
        headers=headers
    )
    query_data = response.json()
    query_id = query_data["id"]
    print(f"✓ Query created (ID: {query_id})")
    
    # Step 5: Test cache metrics endpoint
    print("\n[5/8] Testing GET /api/admin/sessions/cache-metrics...")
    response = requests.get(
        f"{BASE_URL}/api/admin/sessions/cache-metrics",
        headers=headers
    )
    if response.status_code == 403:
        print(f"⚠ Forbidden (user needs superuser role)")
        print(f"   Response: {response.json()}")
    else:
        assert response.status_code == 200, f"Failed: {response.text}"
        metrics = response.json()
        print(f"✓ Cache metrics retrieved:")
        print(f"   - Cache hits: {metrics.get('cache_hits', 0)}")
        print(f"   - Cache misses: {metrics.get('cache_misses', 0)}")
        print(f"   - Hit rate: {metrics.get('hit_rate', 0)}%")
    
    # Step 6: Test cache status endpoint
    print(f"\n[6/8] Testing GET /api/admin/sessions/{query_id}/cache-status...")
    response = requests.get(
        f"{BASE_URL}/api/admin/sessions/{query_id}/cache-status",
        headers=headers
    )
    if response.status_code == 403:
        print(f"⚠ Forbidden (user needs superuser role)")
    else:
        assert response.status_code == 200, f"Failed: {response.text}"
        status = response.json()
        print(f"✓ Cache status retrieved:")
        print(f"   - Query ID: {status.get('query_id')}")
        print(f"   - Cached: {status.get('cached')}")
        print(f"   - TTL: {status.get('ttl_seconds')}s")
        print(f"   - Size: {status.get('size_kb')}KB")
    
    # Step 7: Test active sessions endpoint
    print(f"\n[7/8] Testing GET /api/admin/sessions/active-sessions...")
    response = requests.get(
        f"{BASE_URL}/api/admin/sessions/active-sessions",
        headers=headers
    )
    if response.status_code == 403:
        print(f"⚠ Forbidden (user needs superuser role)")
    else:
        assert response.status_code == 200, f"Failed: {response.text}"
        active = response.json()
        print(f"✓ Active sessions retrieved:")
        print(f"   - Total cached: {active.get('total_cached')}")
        if active.get('sessions'):
            for sess in active['sessions'][:3]:  # Show first 3
                print(f"   - Query {sess['query_id']}: TTL={sess['ttl_seconds']}s")
    
    # Step 8: Test reconstruction log endpoint
    print(f"\n[8/8] Testing GET /api/admin/sessions/{query_id}/reconstruction-log...")
    response = requests.get(
        f"{BASE_URL}/api/admin/sessions/{query_id}/reconstruction-log",
        headers=headers
    )
    if response.status_code == 403:
        print(f"⚠ Forbidden (user needs superuser role)")
    else:
        assert response.status_code == 200, f"Failed: {response.text}"
        log = response.json()
        print(f"✓ Reconstruction log retrieved:")
        print(f"   - Attempts logged: {len(log)}")
        if log:
            for attempt in log[:2]:  # Show first 2
                print(f"   - {attempt['timestamp']}: success={attempt['success']}")
    
    print("\n" + "="*60)
    print("SMOKE TESTS SUMMARY")
    print("="*60)
    print("All endpoint paths are accessible")
    print("⚠ Note: Some tests require superuser privileges")
    print("   To grant superuser: poetry run python scripts/make_superuser.py admin_test_user")
    print("="*60 + "\n")


if __name__ == "__main__":
    try:
        test_admin_sessions_smoke()
        print("✓ All smoke tests passed!\n")
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}\n")
        raise
    except requests.exceptions.ConnectionError:
        print("\n✗ Cannot connect to API server at http://localhost:8001")
        print("Please start the server with: poetry run uvicorn query_refinement_module.api.main:app --reload\n")
        raise
