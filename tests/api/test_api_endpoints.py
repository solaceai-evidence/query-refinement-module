"""
Comprehensive API endpoint testing script.
Tests all authentication, query management, and feedback endpoints.
"""
import requests
import json
import os
import time
from typing import Dict

BASE_URL = "http://localhost:8000"
DB_PATH = "query_refinement.db"

# Store test data
test_data = {
    "access_token": None,
    "user_id": None,
    "session_id": None,
    "query_id": None,
    "refinement_step_id": None,
    "followup_id": None,
    "feedback_id": None
}


def check_api_health():
    """
    Check if the API is running and healthy.
    For clean test runs, use the run_api_tests.sh script which handles database reset.
    """
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✅ API is running and healthy")
            if os.path.exists(DB_PATH):
                print(f"📁 Using database: {DB_PATH}")
            else:
                print("📁 Fresh database will be created")
            return True
        else:
            print(f"⚠️  API health check returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Could not connect to API: {e}")
        print(f"   Make sure the API server is running at {BASE_URL}")
        print("   Quick start: ./run_api_tests.sh")
        print("   Or manually: poetry run uvicorn query_refinement_module.api.main:app --reload")
        return False


def print_response(step: str, response: requests.Response):
    """Print formatted response."""
    print(f"\n{'=' * 60}")
    print(f"STEP: {step}")
    print(f"Status: {response.status_code}")
    if response.status_code < 400:
        print(f" SUCCESS")
        try:
            print(f"Response: {json.dumps(response.json(), indent=2)}")
        except:
            print(f"Response: {response.text}")
    else:
        print(f" FAILED")
        print(f"Error: {response.text}")
    print('=' * 60)
    return response


def get_auth_headers() -> Dict[str, str]:
    """Get authorization headers with JWT token."""
    if test_data["access_token"]:
        return {"Authorization": f"Bearer {test_data['access_token']}"}
    return {}


def test_1_register_user():
    """Test user registration."""
    payload = {
        "email": "test@example.com",
        "name": "Test User",
        "password": "TestPass123!"
    }
    response = requests.post(f"{BASE_URL}/api/auth/register", json=payload)
    result = print_response("1. Register User", response)
    
    if response.status_code == 200:
        data = response.json()
        test_data["user_id"] = data.get("id")
    return result


def test_2_login():
    """Test user login and get JWT token."""
    payload = {
        "username": "test@example.com",  # OAuth2 uses 'username' field
        "password": "TestPass123!"
    }
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        data=payload,  # Form data, not JSON
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    result = print_response("2. Login", response)
    
    if response.status_code == 200:
        data = response.json()
        test_data["access_token"] = data.get("access_token")
        print(f"\n Access Token: {test_data['access_token'][:50]}...")
    return result


def test_3_get_current_user():
    """Test getting current user info."""
    response = requests.get(
        f"{BASE_URL}/api/auth/me",
        headers=get_auth_headers()
    )
    return print_response("3. Get Current User (/me)", response)


def test_4_create_session():
    """Test creating a query session."""
    response = requests.post(
        f"{BASE_URL}/api/queries/sessions",
        headers=get_auth_headers()
    )
    result = print_response("4. Create Query Session", response)
    
    if response.status_code in [200, 201]:
        data = response.json()
        test_data["session_id"] = data.get("id")
    return result


def test_5_list_sessions():
    """Test listing user's sessions."""
    response = requests.get(
        f"{BASE_URL}/api/queries/sessions",
        headers=get_auth_headers()
    )
    return print_response("5. List Sessions", response)


def test_6_get_session():
    """Test getting session details."""
    if not test_data["session_id"]:
        print("\n  Skipping - no session_id")
        return None
    
    response = requests.get(
        f"{BASE_URL}/api/queries/sessions/{test_data['session_id']}",
        headers=get_auth_headers()
    )
    return print_response("6. Get Session Details", response)


def test_7_create_query():
    """Test creating a query."""
    if not test_data["session_id"]:
        print("\n  Skipping - no session_id")
        return None
    
    payload = {
        "session_id": test_data["session_id"],
        "original_query": "What are the effects of exercise on mental health in adults?"
    }
    response = requests.post(
        f"{BASE_URL}/api/queries/",
        json=payload,
        headers=get_auth_headers()
    )
    result = print_response("7. Create Query", response)
    
    if response.status_code in [200, 201]:
        data = response.json()
        test_data["query_id"] = data.get("id")
    return result


def test_8_get_query():
    """Test getting query details."""
    if not test_data["query_id"]:
        print("\n  Skipping - no query_id")
        return None
    
    response = requests.get(
        f"{BASE_URL}/api/queries/{test_data['query_id']}",
        headers=get_auth_headers()
    )
    return print_response("8. Get Query Details", response)


def test_9_update_query():
    """Test updating refined query."""
    if not test_data["query_id"]:
        print("\n  Skipping - no query_id")
        return None
    
    payload = {
        "refined_query": "What are the psychological and emotional effects of regular aerobic exercise on mental health outcomes in adults aged 18-65?"
    }
    response = requests.put(
        f"{BASE_URL}/api/queries/{test_data['query_id']}",
        json=payload,
        headers=get_auth_headers()
    )
    return print_response("9. Update Refined Query", response)


def test_10_create_refinement_step():
    """Test creating a refinement step."""
    if not test_data["query_id"]:
        print("\n  Skipping - no query_id")
        return None
    
    payload = {
        "query_id": test_data["query_id"],
        "aspect_name": "Population"
    }
    response = requests.post(
        f"{BASE_URL}/api/queries/refinement-steps",
        json=payload,
        headers=get_auth_headers()
    )
    result = print_response("10. Create Refinement Step", response)
    
    if response.status_code in [200, 201]:
        data = response.json()
        test_data["refinement_step_id"] = data.get("id")
    return result


def test_11_list_refinement_steps():
    """Test listing refinement steps for a query."""
    if not test_data["query_id"]:
        print("\n  Skipping - no query_id")
        return None
    
    response = requests.get(
        f"{BASE_URL}/api/queries/{test_data['query_id']}/refinement-steps",
        headers=get_auth_headers()
    )
    return print_response("11. List Refinement Steps", response)


def test_12_create_followup():
    """Test creating a follow-up entry."""
    if not test_data["refinement_step_id"]:
        print("\n  Skipping - no refinement_step_id")
        return None
    
    payload = {
        "refinement_step_id": test_data["refinement_step_id"],
        "question": "Can you specify the age range for the population?",
        "answer": "Adults aged 18-65 years"
    }
    response = requests.post(
        f"{BASE_URL}/api/queries/followups",
        json=payload,
        headers=get_auth_headers()
    )
    result = print_response("12. Create Follow-up", response)
    
    if response.status_code in [200, 201]:
        data = response.json()
        test_data["followup_id"] = data.get("id")
    return result


def test_13_update_followup():
    """Test updating a follow-up answer."""
    if not test_data["followup_id"]:
        print("\n  Skipping - no followup_id")
        return None
    
    payload = {
        "answer": "Adults aged 18-65 years, excluding those with severe mental illness"
    }
    response = requests.put(
        f"{BASE_URL}/api/queries/followups/{test_data['followup_id']}",
        json=payload,
        headers=get_auth_headers()
    )
    return print_response("13. Update Follow-up Answer", response)


def test_14_submit_feedback():
    """Test submitting feedback."""
    if not test_data["query_id"]:
        print("\n  Skipping - no query_id")
        return None
    
    payload = {
        "query_id": test_data["query_id"],
        "rating": 5,
        "comments": "The refinement process was very helpful and intuitive!"
    }
    response = requests.post(
        f"{BASE_URL}/api/feedback/",
        json=payload,
        headers=get_auth_headers()
    )
    result = print_response("14. Submit Feedback", response)
    
    if response.status_code in [200, 201]:
        data = response.json()
        test_data["feedback_id"] = data.get("id")
    return result


def test_15_get_my_feedback():
    """Test getting user's feedback."""
    response = requests.get(
        f"{BASE_URL}/api/feedback/my-feedback",
        headers=get_auth_headers()
    )
    return print_response("15. Get My Feedback", response)


def test_16_get_query_feedback():
    """Test getting feedback for a specific query."""
    if not test_data["query_id"]:
        print("\n  Skipping - no query_id")
        return None
    
    response = requests.get(
        f"{BASE_URL}/api/feedback/query/{test_data['query_id']}",
        headers=get_auth_headers()
    )
    return print_response("16. Get Query Feedback", response)


def test_17_end_session():
    """Test ending a session."""
    if not test_data["session_id"]:
        print("\n  Skipping - no session_id")
        return None
    
    response = requests.post(
        f"{BASE_URL}/api/queries/sessions/{test_data['session_id']}/end",
        headers=get_auth_headers()
    )
    return print_response("17. End Session", response)


def test_18_health_check():
    """Test health check endpoint."""
    response = requests.get(f"{BASE_URL}/health")
    return print_response("18. Health Check", response)


def run_all_tests():
    """Run all API tests in sequence."""
    print("\n" + "=" * 60)
    print("🧪 STARTING COMPREHENSIVE API TESTS")
    print("=" * 60)
    
    # Check if API is healthy before running tests
    if not check_api_health():
        print("\n❌ Cannot run tests - API is not available")
        return
    
    tests = [
        test_1_register_user,
        test_2_login,
        test_3_get_current_user,
        test_4_create_session,
        test_5_list_sessions,
        test_6_get_session,
        test_7_create_query,
        test_8_get_query,
        test_9_update_query,
        test_10_create_refinement_step,
        test_11_list_refinement_steps,
        test_12_create_followup,
        test_13_update_followup,
        test_14_submit_feedback,
        test_15_get_my_feedback,
        test_16_get_query_feedback,
        test_17_end_session,
        test_18_health_check,
    ]
    
    passed = 0
    failed = 0
    skipped = 0
    
    for test in tests:
        try:
            result = test()
            if result is None:
                skipped += 1
            elif result.status_code < 400:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"\n EXCEPTION in {test.__name__}: {str(e)}")
            failed += 1
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Skipped: {skipped}")
    print(f"Total: {passed + failed + skipped}")
    print("=" * 60)
    
    print("\nTest Data Captured:")
    print(json.dumps(test_data, indent=2))


if __name__ == "__main__":
    try:
        run_all_tests()
    except KeyboardInterrupt:
        print("\n\n  Tests interrupted by user")
    except Exception as e:
        print(f"\n\n Unexpected error: {str(e)}")
