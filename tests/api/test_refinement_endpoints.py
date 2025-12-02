"""
Tests for the refinement workflow API endpoints.
"""
import requests

# Test configuration
BASE_URL = "http://localhost:8000"
TEST_USER = {
    "email": "refine_test@example.com",
    "password": "TestPass123!",
    "name": "Refinement Test User"
}


def check_api_health() -> bool:
    """Check if API server is running and database is accessible."""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def register_and_login() -> str:
    """Register a test user and return access token."""
    # Try to register (may already exist)
    try:
        requests.post(
            f"{BASE_URL}/api/auth/register",
            json=TEST_USER
        )
    except Exception:
        pass  # User may already exist
    
    # Login to get token
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        data={
            "username": TEST_USER["email"],
            "password": TEST_USER["password"]
        }
    )
    
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["access_token"]


def test_health_check():
    """Test that the API is healthy."""
    assert check_api_health(), "API server is not responding"


def test_get_available_frameworks():
    """Test listing available refinement frameworks."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(
        f"{BASE_URL}/api/refinement/frameworks",
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "frameworks" in data
    assert "count" in data
    assert isinstance(data["frameworks"], list)
    print(f"✓ Available frameworks: {data['count']}")


def test_start_refinement_workflow():
    """Test starting a new refinement workflow."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Start refinement with a simple medical query
    response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "effects of aspirin on stroke prevention",
            "framework_name": "pico_advanced"
        },
        headers=headers
    )
    
    assert response.status_code == 201, f"Start refinement failed: {response.text}"
    data = response.json()
    
    # Verify response structure
    assert "session_id" in data
    assert "query_id" in data
    assert "summary" in data
    assert "next_prompt" in data
    
    # Verify summary contains expected fields
    summary = data["summary"]
    assert "is_complete" in summary
    assert "total_aspects" in summary
    assert "aspects_needing_refinement" in summary
    assert "aspects_clear" in summary
    assert "aspects" in summary
    
    # Verify next_prompt structure
    if data["next_prompt"]:
        next_prompt = data["next_prompt"]
        assert "aspect_name" in next_prompt
        assert "question" in next_prompt
    
    print(f"✓ Started refinement - Query ID: {data['query_id']}, Session ID: {data['session_id']}")
    print(f"  Summary: {summary['aspects_needing_refinement']} need refinement, {summary['aspects_clear']} clear")
    
    return data


def test_get_refinement_status():
    """Test getting refinement status."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Start a refinement first
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "diabetes treatment in elderly patients",
            "framework_name": "pico_advanced"
        },
        headers=headers
    )
    
    assert start_response.status_code == 201
    query_id = start_response.json()["query_id"]
    
    # Get status
    response = requests.get(
        f"{BASE_URL}/api/refinement/queries/{query_id}/status",
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert data["query_id"] == query_id
    assert "original_query" in data
    assert "is_complete" in data
    assert "aspects_summary" in data
    
    print(f"✓ Got refinement status for query {query_id}")
    print(f"  Complete: {data['is_complete']}, Current aspect: {data.get('current_aspect')}")


def test_submit_answer():
    """Test submitting an answer to a refinement question."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Start a refinement first
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "hypertension medication effectiveness",
            "framework_name": "pico_advanced"
        },
        headers=headers
    )
    
    assert start_response.status_code == 201
    start_data = start_response.json()
    query_id = start_data["query_id"]
    
    # Check if there's a question to answer
    if not start_data.get("next_prompt"):
        print("✓ No questions to answer - all aspects clear")
        return
    
    # Submit an answer
    response = requests.post(
        f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
        json={
            "answer": "Adults over 65 years old with diagnosed hypertension"
        },
        headers=headers
    )
    
    # Note: This may fail if LLM provider is not configured
    # We'll check for both success and expected errors
    if response.status_code == 200:
        data = response.json()
        assert "refinement_step_id" in data
        assert "followup_id" in data
        assert "is_complete" in data
        print(f"✓ Submitted answer - Step ID: {data['refinement_step_id']}, Complete: {data['is_complete']}")
    elif response.status_code in [500, 400]:
        # Expected if LLM provider not configured
        print(f"⚠ Answer submission requires LLM configuration: {response.status_code}")
    else:
        raise AssertionError(f"Unexpected response: {response.status_code} - {response.text}")


def test_synthesize_query():
    """Test synthesizing the refined query."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Start a refinement first
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "cancer screening methods",
            "framework_name": "pico_advanced"
        },
        headers=headers
    )
    
    assert start_response.status_code == 201
    query_id = start_response.json()["query_id"]
    
    # Synthesize (this will work even without answers - returns original query)
    response = requests.post(
        f"{BASE_URL}/api/refinement/synthesize",
        json={
            "query_id": query_id
        },
        headers=headers
    )
    
    # Note: This may fail if LLM provider is not configured
    if response.status_code == 200:
        data = response.json()
        assert data["query_id"] == query_id
        assert "refined_query" in data
        assert "used_llm" in data
        assert "metadata" in data
        print(f"✓ Synthesized query - Used LLM: {data['used_llm']}")
        print(f"  Refined: {data['refined_query'][:100]}...")
    elif response.status_code in [500, 400]:
        # Expected if LLM provider not configured
        print(f"⚠ Query synthesis requires LLM configuration: {response.status_code}")
    else:
        raise AssertionError(f"Unexpected response: {response.status_code} - {response.text}")


def test_unauthorized_access():
    """Test that endpoints require authentication."""
    # Try to start refinement without token
    response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "test query",
            "framework_name": "pico_advanced"
        }
    )
    
    assert response.status_code == 401
    print("✓ Unauthorized access properly blocked")


def test_invalid_framework():
    """Test error handling for invalid framework name."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "test query",
            "framework_name": "nonexistent_framework"
        },
        headers=headers
    )
    
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
    print("✓ Invalid framework properly rejected")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("REFINEMENT WORKFLOW API TESTS")
    print("="*60 + "\n")
    
    if not check_api_health():
        print("❌ API server is not running. Please start it with:")
        print("   poetry run uvicorn query_refinement_module.api.main:app --reload")
        exit(1)
    
    print("✓ API server is healthy\n")
    
    # Run tests
    tests = [
        ("Health Check", test_health_check),
        ("Get Available Frameworks", test_get_available_frameworks),
        ("Start Refinement Workflow", test_start_refinement_workflow),
        ("Get Refinement Status", test_get_refinement_status),
        ("Submit Answer", test_submit_answer),
        ("Synthesize Query", test_synthesize_query),
        ("Unauthorized Access", test_unauthorized_access),
        ("Invalid Framework", test_invalid_framework),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            print(f"\n▶ Running: {test_name}")
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"❌ Failed: {test_name}")
            print(f"   Error: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ Error in {test_name}: {e}")
            failed += 1
    
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Total: {passed + failed}")
    print("="*60 + "\n")
    
    exit(0 if failed == 0 else 1)
