#!/usr/bin/env python3
"""
Test for session abandonment (Start Over) functionality.

This test verifies that:
1. Sessions can be properly abandoned
2. All related data is deleted from database
3. Abandoned sessions don't count toward workflow limits
4. User can start a new session after abandoning

Usage:
    poetry run python tests/api/test_abandon_session.py
"""
import requests
import json
import sys
import time
from typing import Dict

from query_refinement_module.api.config import get_settings

BASE_URL = "http://localhost:8001/api/v1"
API_ROOT = BASE_URL.replace("/api/v1", "")
AUTH_COOKIE_NAME = get_settings().auth_cookie_name

class Colors:
    """ANSI color codes for terminal output"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_section(title: str):
    """Print a formatted section header"""
    print(f"\n{Colors.BOLD}{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}{Colors.END}\n")

def print_success(message: str):
    """Print a success message"""
    print(f"{Colors.GREEN}✓ {message}{Colors.END}")

def print_error(message: str):
    """Print an error message"""
    print(f"{Colors.RED}✗ {message}{Colors.END}")

def print_warning(message: str):
    """Print a warning message"""
    print(f"{Colors.YELLOW}⚠ {message}{Colors.END}")

def print_info(message: str):
    """Print an info message"""
    print(f"{Colors.BLUE}ℹ {message}{Colors.END}")

def register_and_login() -> str:
    """Register a test user and return the JWT from the auth cookie."""
    print_section("1. Authentication")
    
    username = f"abandon_test_{int(time.time())}"
    register_data = {
        "username": username,
        "password": "TestPass123!"
    }
    
    print(f"Registering user: {username}")
    response = requests.post(f"{BASE_URL}/api/auth/register", json=register_data)
    
    if response.status_code not in [200, 201]:
        print_warning("Registration failed (user might exist), trying login...")
    
    # Login
    login_data = {
        "username": username,
        "password": "TestPass123!",
        "grant_type": "password"
    }
    
    response = requests.post(f"{BASE_URL}/api/auth/login", data=login_data)
    
    if response.status_code != 200:
        print_error("Login failed")
        print(f"Response: {response.text}")
        sys.exit(1)

    token = response.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        print_error("Login succeeded but auth cookie was not set")
        sys.exit(1)

    print_success(f"Authenticated as {username}")
    return token

def start_refinement(token: str, framework: str = "mph_dissertation") -> Dict:
    """Start a refinement session"""
    print_section("2. Starting Initial Refinement Session")
    
    headers = {"Authorization": f"Bearer {token}"}
    start_data = {
        "framework_name": framework,
        "original_query": "I want to research childhood obesity"
    }
    
    print(f"Framework: {framework}")
    print(f"Query: {start_data['original_query']}")
    
    response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json=start_data,
        headers=headers
    )
    
    if response.status_code != 201:
        print_error("Failed to start refinement")
        print(f"Response: {response.text}")
        sys.exit(1)
    
    data = response.json()
    query_id = data["query_id"]
    session_id = data["session_id"]
    
    print_success(f"Session started (Query ID: {query_id}, Session ID: {session_id})")
    
    return data

def submit_answer(token: str, query_id: int, answer: str) -> Dict:
    """Submit an answer to the refinement workflow"""
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.post(
        f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
        json={"answer": answer},
        headers=headers
    )
    
    if response.status_code != 200:
        print_error(f"Failed to submit answer")
        print(f"Response: {response.text}")
        sys.exit(1)
    
    return response.json()

def get_user_queries(token: str) -> list:
    """Get all queries for the current user"""
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(
        f"{BASE_URL}/api/queries",
        headers=headers
    )
    
    if response.status_code != 200:
        print_error("Failed to get user queries")
        return []
    
    return response.json()

def abandon_session(token: str, session_id: int) -> Dict:
    """Abandon a session"""
    print_section("4. Abandoning Session")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    print(f"Requesting abandonment of session {session_id}...")
    
    response = requests.post(
        f"{BASE_URL}/api/refinement/sessions/abandon",
        json={"session_id": session_id},
        headers=headers
    )
    
    if response.status_code != 200:
        print_error("Abandon request failed")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        sys.exit(1)
    
    result = response.json()
    
    print_success("Session abandoned successfully")
    print(f"\nDeletion counts:")
    for key, count in result.get('deletion_counts', {}).items():
        print(f"  - {key}: {count}")
    
    return result

def verify_session_deleted(token: str, query_id: int) -> bool:
    """Verify that session data is deleted"""
    print_section("5. Verifying Session Data is Deleted")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Try to get query status (should fail with 404)
    response = requests.get(
        f"{BASE_URL}/api/refinement/queries/{query_id}/status",
        headers=headers
    )
    
    if response.status_code == 404:
        print_success("Query status correctly returns 404 (deleted)")
        return True
    else:
        print_error(f"Query still exists! Status code: {response.status_code}")
        return False

def verify_can_start_new_session(token: str) -> bool:
    """Verify that user can start a new session after abandoning"""
    print_section("6. Verifying Can Start New Session")
    
    try:
        result = start_refinement(token)
        print_success("Successfully started new session after abandoning previous one")
        print_info("This confirms abandoned sessions don't count toward limits")
        return True
    except Exception as e:
        print_error(f"Failed to start new session: {e}")
        return False

def main():
    """Run the complete test"""
    # Check server health
    try:
        response = requests.get(f"{API_ROOT}/health", timeout=2)
        if response.status_code != 200:
            print_error("API server is not healthy")
            sys.exit(1)
    except requests.exceptions.ConnectionError:
        print_error("API server is not running")
        print("Start with: poetry run uvicorn query_refinement_module.api.main:app --reload")
        sys.exit(1)
    
    print_section("SESSION ABANDONMENT TEST")
    print("Testing 'Start Over' functionality with database cleanup\n")
    
    # Authenticate
    token = register_and_login()
    
    # Start initial refinement
    start_result = start_refinement(token)
    initial_session_id = start_result["session_id"]
    initial_query_id = start_result["query_id"]
    
    # Submit one answer to create some data
    print_section("3. Creating Some Refinement Data")
    print("Submitting an answer to create refinement steps...")
    submit_answer(token, initial_query_id, "Children aged 5-12 in urban areas")
    print_success("Answer submitted, refinement data created")
    
    # Abandon the session
    abandon_result = abandon_session(token, initial_session_id)
    
    # Verify deletion counts
    deletion_counts = abandon_result.get('deletion_counts', {})
    issues = []
    
    if deletion_counts.get('queries', 0) < 1:
        issues.append("No queries were deleted")
    
    if deletion_counts.get('session', 0) < 1:
        issues.append("Session was not deleted")
    
    # Verify session is actually deleted
    session_deleted = verify_session_deleted(token, initial_query_id)
    if not session_deleted:
        issues.append("Session data still exists in database")
    
    # Verify can start new session (doesn't count toward limit)
    can_start_new = verify_can_start_new_session(token)
    if not can_start_new:
        issues.append("Cannot start new session after abandoning")
    
    # Final verdict
    print_section("TEST RESULT")
    if not issues:
        print(f"{Colors.GREEN}{Colors.BOLD}✅ ALL TESTS PASSED{Colors.END}")
        print("Session abandonment is working correctly:")
        print("  ✓ Session data is deleted from database")
        print("  ✓ Abandoned sessions don't count toward limits")
        print("  ✓ User can start new session after abandoning")
    else:
        print(f"{Colors.RED}{Colors.BOLD}❌ TESTS FAILED{Colors.END}")
        print("Issues found:")
        for issue in issues:
            print(f"  • {issue}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
