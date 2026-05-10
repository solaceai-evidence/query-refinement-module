"""
Tests for feedback and query history API endpoints.
"""
import requests
from query_refinement_module.api.config import get_settings
from .test_refinement_endpoints import BASE_URL, register_and_login, check_api_health

AUTH_COOKIE_NAME = get_settings().auth_cookie_name


def test_submit_feedback_with_rating_and_comments():
    """Test submitting feedback with both rating and comments."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Create a query first
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
    
    # Submit feedback
    response = requests.post(
        f"{BASE_URL}/api/feedback/",
        json={
            "query_id": query_id,
            "rating": 5,
            "comments": "Very helpful refinement process!"
        },
        headers=headers
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["rating"] == 5
    assert data["comments"] == "Very helpful refinement process!"
    assert data["query_id"] == query_id
    print("✓ Feedback with rating and comments submitted successfully")


def test_submit_feedback_rating_only():
    """Test submitting feedback with only a rating."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Create a query first
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "diabetes treatment options",
            "framework_name": "pico_advanced"
        },
        headers=headers
    )
    query_id = start_response.json()["query_id"]
    
    # Submit feedback with only rating
    response = requests.post(
        f"{BASE_URL}/api/feedback/",
        json={
            "query_id": query_id,
            "rating": 4
        },
        headers=headers
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["rating"] == 4
    assert data["query_id"] == query_id
    print("✓ Feedback with rating only submitted successfully")


def test_submit_feedback_comments_only():
    """Test submitting feedback with only comments."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Create a query
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "heart disease prevention",
            "framework_name": "pico_advanced"
        },
        headers=headers
    )
    query_id = start_response.json()["query_id"]
    
    # Submit feedback with only comments
    response = requests.post(
        f"{BASE_URL}/api/feedback/",
        json={
            "query_id": query_id,
            "comments": "The refinement questions were very specific."
        },
        headers=headers
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["comments"] == "The refinement questions were very specific."
    print("✓ Feedback with comments only submitted successfully")


def test_submit_general_feedback():
    """Test submitting general feedback not tied to a specific query."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.post(
        f"{BASE_URL}/api/feedback/",
        json={
            "rating": 5,
            "comments": "Great tool overall!"
        },
        headers=headers
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["rating"] == 5
    assert data["comments"] == "Great tool overall!"
    assert data["query_id"] is None
    print("✓ General feedback submitted successfully")


def test_submit_feedback_invalid_query():
    """Test submitting feedback for a non-existent query."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.post(
        f"{BASE_URL}/api/feedback/",
        json={
            "query_id": 99999,
            "rating": 3,
            "comments": "Test"
        },
        headers=headers
    )
    
    assert response.status_code == 404
    print("✓ Feedback for invalid query properly rejected")


def test_get_my_feedback():
    """Test retrieving user's own feedback."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Submit some feedback
    requests.post(
        f"{BASE_URL}/api/feedback/",
        json={"rating": 5, "comments": "Test feedback 1"},
        headers=headers
    )
    requests.post(
        f"{BASE_URL}/api/feedback/",
        json={"rating": 4, "comments": "Test feedback 2"},
        headers=headers
    )
    
    # Get feedback
    response = requests.get(
        f"{BASE_URL}/api/feedback/my-feedback",
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 2  # At least the two we just submitted
    print(f"✓ Retrieved {len(data)} feedback items")


def test_get_feedback_for_query():
    """Test retrieving feedback for a specific query."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Create a query
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "asthma treatment",
            "framework_name": "pico_advanced"
        },
        headers=headers
    )
    query_id = start_response.json()["query_id"]
    
    # Submit multiple feedback for this query
    requests.post(
        f"{BASE_URL}/api/feedback/",
        json={"query_id": query_id, "rating": 5},
        headers=headers
    )
    requests.post(
        f"{BASE_URL}/api/feedback/",
        json={"query_id": query_id, "comments": "Follow-up feedback"},
        headers=headers
    )
    
    # Get feedback for query
    response = requests.get(
        f"{BASE_URL}/api/feedback/query/{query_id}",
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 2
    print(f"✓ Retrieved {len(data)} feedback items for query")


def test_get_user_queries():
    """Test retrieving user's query history."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Create multiple queries
    queries_created = []
    for i, query_text in enumerate([
        "depression treatment in adolescents",
        "vaccine efficacy studies",
        "antibiotic resistance patterns"
    ]):
        response = requests.post(
            f"{BASE_URL}/api/refinement/start",
            json={
                "original_query": query_text,
                "framework_name": "pico_advanced"
            },
            headers=headers
        )
        assert response.status_code == 201
        queries_created.append(response.json()["query_id"])
    
    # Get user's sessions (which contain queries)
    response = requests.get(
        f"{BASE_URL}/api/queries/sessions",
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 3  # At least the three sessions we just created
    
    # Each session should have our queries
    print(f"✓ Retrieved {len(data)} sessions for user")


def test_get_specific_query():
    """Test retrieving a specific query by ID."""
    token = register_and_login()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Create a query
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "migraine prevention strategies",
            "framework_name": "pico_advanced"
        },
        headers=headers
    )
    query_id = start_response.json()["query_id"]
    
    # Get the specific query
    response = requests.get(
        f"{BASE_URL}/api/queries/{query_id}",
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == query_id
    assert data["original_query"] == "migraine prevention strategies"
    print("✓ Retrieved specific query successfully")


def test_cannot_access_other_users_queries():
    """Test that users cannot access other users' queries."""
    # Create first user and their query
    token1 = register_and_login()
    headers1 = {"Authorization": f"Bearer {token1}"}
    
    start_response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={
            "original_query": "user 1 query",
            "framework_name": "pico_advanced"
        },
        headers=headers1
    )
    query_id = start_response.json()["query_id"]
    
    # Create second user with unique credentials
    import time
    timestamp = int(time.time() * 1000)
    test_user_2 = {
        "username": f"history_test2_{timestamp}",
        "email": f"history_test2_{timestamp}@example.com",
        "password": "TestPass123!",
        "name": "History Test User 2"
    }
    requests.post(f"{BASE_URL}/api/auth/register", json=test_user_2)
    
    login_response = requests.post(
        f"{BASE_URL}/api/auth/login",
        data={"username": test_user_2["username"], "password": test_user_2["password"]}
    )
    assert login_response.status_code == 200, f"Login failed: {login_response.text}"
    token2 = login_response.cookies.get(AUTH_COOKIE_NAME)
    assert token2 is not None
    headers2 = {"Authorization": f"Bearer {token2}"}
    
    # Try to access user 1's query with user 2's token
    response = requests.get(
        f"{BASE_URL}/api/queries/{query_id}",
        headers=headers2
    )
    
    assert response.status_code == 403  # Forbidden
    print("✓ Cross-user query access properly blocked")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("FEEDBACK AND QUERY HISTORY TESTS")
    print("="*60 + "\n")
    
    if not check_api_health():
        print("❌ API server is not running")
        exit(1)
    
    print("✓ API server is healthy\n")
    
    tests = [
        ("Submit Feedback (Rating + Comments)", test_submit_feedback_with_rating_and_comments),
        ("Submit Feedback (Rating Only)", test_submit_feedback_rating_only),
        ("Submit Feedback (Comments Only)", test_submit_feedback_comments_only),
        ("Submit General Feedback", test_submit_general_feedback),
        ("Submit Feedback for Invalid Query", test_submit_feedback_invalid_query),
        ("Get My Feedback", test_get_my_feedback),
        ("Get Feedback for Query", test_get_feedback_for_query),
        ("Get User Queries", test_get_user_queries),
        ("Get Specific Query", test_get_specific_query),
        ("Cannot Access Other Users' Queries", test_cannot_access_other_users_queries),
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
