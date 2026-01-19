"""
Tests for the refinement workflow API endpoints.
"""
import requests

# Test configuration
BASE_URL = "http://localhost:8000"
TEST_USER = {
    "username": "refine_test_user",
    "email": "refine_test@example.com",
    "password": "TestPass123!"
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
            "username": TEST_USER["username"],
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


def test_command_status():
    """Test /status command returns session summary."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Start a refinement session
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "effects of aspirin on stroke prevention",
            "framework_name": "pico_advanced"
        },
        headers=headers
    )
    assert start_response.status_code == 201
    query_id = start_response.json()["query_id"]
    
    # Send /status command
    response = requests.post(
        f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
        json={"answer": "/status"},
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify it's a command response
    assert "command_type" in data
    assert data["command_type"] == "status"
    assert data["success"] is True
    assert "message" in data
    assert "step_summary" in data
    assert "next_prompt" in data
    
    # Verify step summary structure
    summary = data["step_summary"]
    assert "total_steps" in summary
    assert "completed" in summary
    
    print("✓ /status command returns session summary")


def test_command_steps():
    """Test /steps command returns list of all steps."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Start a refinement session
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "effects of aspirin on stroke prevention",
            "framework_name": "pico_advanced"
        },
        headers=headers
    )
    assert start_response.status_code == 201
    query_id = start_response.json()["query_id"]
    
    # Send /steps command
    response = requests.post(
        f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
        json={"answer": "/steps"},
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify it's a command response
    assert data["command_type"] == "steps"
    assert data["success"] is True
    assert "step_list" in data
    assert isinstance(data["step_list"], list)
    assert len(data["step_list"]) > 0
    
    print("✓ /steps command returns list of steps")


def test_command_help():
    """Test /help command returns help text."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Start a refinement session
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "effects of aspirin on stroke prevention",
            "framework_name": "pico_advanced"
        },
        headers=headers
    )
    assert start_response.status_code == 201
    query_id = start_response.json()["query_id"]
    
    # Send /help command
    response = requests.post(
        f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
        json={"answer": "/help"},
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify it's a command response
    assert data["command_type"] == "help"
    assert data["success"] is True
    assert "message" in data
    assert "NAVIGATION" in data["message"] or "navigation" in data["message"].lower()
    
    print("✓ /help command returns help text")


def test_command_skip():
    """Test /skip command advances to next aspect."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Start a refinement session
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "effects of aspirin on stroke prevention",
            "framework_name": "pico_advanced"
        },
        headers=headers
    )
    assert start_response.status_code == 201
    query_id = start_response.json()["query_id"]
    first_prompt = start_response.json()["next_prompt"]
    
    # Send /skip command
    response = requests.post(
        f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
        json={"answer": "/skip"},
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify it's a command response
    assert data["command_type"] == "skip"
    assert data["success"] is True
    
    # Verify we moved to next aspect (or completed if only one aspect)
    if data["next_prompt"]:
        assert data["next_prompt"]["aspect_id"] != first_prompt["aspect_id"]
    
    print("✓ /skip command advances workflow")


def test_command_submit():
    """Test /submit command flags session for synthesis."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Start a refinement session
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "effects of aspirin on stroke prevention",
            "framework_name": "pico_advanced"
        },
        headers=headers
    )
    assert start_response.status_code == 201
    query_id = start_response.json()["query_id"]
    
    # Send /submit command
    response = requests.post(
        f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
        json={"answer": "/submit"},
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify it's a command response
    assert data["command_type"] == "submit"
    assert data["success"] is True
    assert data["synthesis_ready"] is True
    assert data["next_prompt"] is None
    
    print("✓ /submit command enables synthesis")


def test_command_back_after_answer():
    """Test /back command returns to previous step."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Start a refinement session
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "effects of aspirin on stroke prevention",
            "framework_name": "pico_advanced"
        },
        headers=headers
    )
    assert start_response.status_code == 201
    query_id = start_response.json()["query_id"]
    first_aspect = start_response.json()["next_prompt"]["aspect_id"]
    
    # Answer first question
    answer_response = requests.post(
        f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
        json={"answer": "Adults over 50 years old"},
        headers=headers
    )
    assert answer_response.status_code == 200
    
    # If we moved to second aspect, go back
    if answer_response.json().get("next_prompt"):
        second_aspect = answer_response.json()["next_prompt"]["aspect_id"]
        if second_aspect != first_aspect:
            # Send /back command
            back_response = requests.post(
                f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
                json={"answer": "/back", "force": True},  # Use force to bypass confirmation
                headers=headers
            )
            
            assert back_response.status_code == 200
            data = back_response.json()
            
            # Verify it's a command response
            assert data["command_type"] in ["back", "prev"]
            assert data["success"] is True
            
            # Verify we're back at first aspect
            if data["next_prompt"]:
                assert data["next_prompt"]["aspect_id"] == first_aspect
    
    print("✓ /back command returns to previous step")


def test_command_invalid():
    """Test invalid command handling."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Start a refinement session
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "effects of aspirin on stroke prevention",
            "framework_name": "pico_advanced"
        },
        headers=headers
    )
    assert start_response.status_code == 201
    query_id = start_response.json()["query_id"]
    
    # Send invalid command
    response = requests.post(
        f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
        json={"answer": "/invalid"},
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Should return error
    assert data["success"] is False
    assert "message" in data
    
    print("✓ Invalid command properly rejected")


def test_command_force_confirmation():
    """Test force confirmation for navigation commands."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Start a refinement session with framework that has dependencies
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "effects of aspirin on stroke prevention",
            "framework_name": "pico_advanced_complete"  # Has dependencies
        },
        headers=headers
    )
    
    # If framework not available, skip test
    if start_response.status_code == 404:
        print("⊘ Skipping force confirmation test (framework not available)")
        return
        
    assert start_response.status_code == 201
    query_id = start_response.json()["query_id"]
    
    # Answer first question to move forward
    requests.post(
        f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
        json={"answer": "Adults over 50 years old"},
        headers=headers
    )
    
    # Try /restart without force flag
    response = requests.post(
        f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
        json={"answer": "/restart", "force": False},
        headers=headers
    )
    
    data = response.json()
    
    # Should require force confirmation if there are invalidated aspects
    if data.get("force_required"):
        assert data["success"] is False
        assert "force=true" in data["message"]
        
        # Now send with force=true
        force_response = requests.post(
            f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
            json={"answer": "/restart", "force": True},
            headers=headers
        )
        
        force_data = force_response.json()
        assert force_data["success"] is True
        
        print("✓ Force confirmation working for navigation commands")
    else:
        print("⊘ Force confirmation not triggered (no dependent aspects)")


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
        ("Command: /status", test_command_status),
        ("Command: /steps", test_command_steps),
        ("Command: /help", test_command_help),
        ("Command: /skip", test_command_skip),
        ("Command: /submit", test_command_submit),
        ("Command: /back", test_command_back_after_answer),
        ("Command: Invalid command", test_command_invalid),
        ("Command: Force confirmation", test_command_force_confirmation),
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
