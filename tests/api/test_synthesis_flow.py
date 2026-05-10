#!/usr/bin/env python3
"""
Comprehensive test for the synthesis result display issue.

This test covers the complete refinement workflow including:
1. Starting a refinement session
2. Answering all questions (or using /submit to complete early)
3. Triggering synthesis
4. Verifying the synthesis result is properly returned and non-empty

Usage:
    poetry run python tests/api/test_synthesis_flow.py
"""
import requests
import json
import sys
import time
from typing import Dict, Optional

from query_refinement_module.api.config import get_settings

BASE_URL = "http://localhost:8001/api/v1"
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

def print_response(response: requests.Response, show_body: bool = True):
    """Print formatted response details"""
    print(f"Status: {response.status_code}")
    if show_body:
        try:
            body = response.json()
            print(f"Body: {json.dumps(body, indent=2)[:500]}...")
        except:
            print(f"Body (text): {response.text[:300]}...")

def register_and_login() -> str:
    """Register a test user and return the JWT from the auth cookie."""
    print_section("1. Authentication")
    
    username = f"synthesis_test_{int(time.time())}"
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
        print_response(response)
        sys.exit(1)

    token = response.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        print_error("Login succeeded but auth cookie was not set")
        sys.exit(1)

    print_success(f"Authenticated as {username}")
    return token

def start_refinement(token: str, framework: str = "mph_dissertation") -> Dict:
    """Start a refinement session"""
    print_section("2. Starting Refinement Session")
    
    headers = {"Authorization": f"Bearer {token}"}
    start_data = {
        "framework_name": framework,
        "original_query": "I want to research childhood obesity in urban areas"
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
        print_response(response)
        sys.exit(1)
    
    data = response.json()
    query_id = data["query_id"]
    session_id = data["session_id"]
    
    print_success(f"Session started (Query ID: {query_id}, Session ID: {session_id})")
    
    if data.get("next_prompt"):
        print(f"First question: {data['next_prompt'].get('aspect_name')}")
    
    if data.get("ready_for_synthesis"):
        print_success("All aspects complete - ready for synthesis immediately!")
    
    return data

def submit_command(token: str, query_id: int, command: str) -> Dict:
    """Submit a command to the refinement workflow"""
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.post(
        f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
        json={"answer": command},
        headers=headers
    )
    
    if response.status_code != 200:
        print_error(f"Failed to submit command: {command}")
        print_response(response)
        sys.exit(1)
    
    return response.json()

def check_ready_for_synthesis(token: str, query_id: int) -> bool:
    """Check if the workflow is ready for synthesis"""
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(
        f"{BASE_URL}/api/refinement/queries/{query_id}/status",
        headers=headers
    )
    
    if response.status_code != 200:
        print_error("Failed to get status")
        return False
    
    status = response.json()
    return status.get("ready_for_synthesis", False)

def synthesize_query(token: str, query_id: int) -> Optional[Dict]:
    """Trigger synthesis and return the result"""
    print_section("4. Synthesizing Refined Query")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    print(f"Requesting synthesis for query {query_id}...")
    
    response = requests.post(
        f"{BASE_URL}/api/refinement/synthesize",
        json={"query_id": query_id},
        headers=headers
    )
    
    if response.status_code != 200:
        print_error("Synthesis request failed")
        print_response(response)
        return None
    
    result = response.json()
    
    print_success("Synthesis request completed")
    print(f"\nSynthesis result structure:")
    print(f"  - query_id: {result.get('query_id')}")
    print(f"  - integrated_statement present: {bool(result.get('integrated_statement'))}")
    print(f"  - integrated_statement type: {type(result.get('integrated_statement'))}")
    print(f"  - integrated_statement length: {len(result.get('integrated_statement', ''))}")
    print(f"  - used_llm: {result.get('used_llm')}")
    print(f"  - structured_output present: {bool(result.get('structured_output'))}")
    
    return result

def validate_synthesis_result(result: Dict) -> bool:
    """Validate that synthesis result is properly formed"""
    print_section("5. Validating Synthesis Result")
    
    issues = []
    
    # Check required fields
    if not result:
        issues.append("Result is None or empty")
        
    if not isinstance(result, dict):
        issues.append(f"Result is not a dict, got {type(result)}")
        
    if not result.get('query_id'):
        issues.append("Missing query_id")
        
    if 'integrated_statement' not in result:
        issues.append("Missing integrated_statement field")
    elif not result['integrated_statement']:
        issues.append("integrated_statement is None or empty")
    elif not isinstance(result['integrated_statement'], str):
        issues.append(f"integrated_statement is not a string, got {type(result['integrated_statement'])}")
    elif not result['integrated_statement'].strip():
        issues.append("integrated_statement is only whitespace")
    
    # Check for raw JSON (common issue)
    integrated_statement = result.get('integrated_statement', '')
    if isinstance(integrated_statement, str):
        if integrated_statement.startswith('{') or integrated_statement.startswith('```json'):
            print_warning("integrated_statement appears to be raw JSON instead of extracted statement")
            issues.append("integrated_statement contains raw JSON - should be extracted from LLM response")
    
    # Print results
    if issues:
        print_error("Validation failed with issues:")
        for issue in issues:
            print(f"  • {issue}")
        return False
    else:
        print_success("Synthesis result is valid!")
        
        # Print preview
        integrated_statement = result['integrated_statement']
        preview = integrated_statement[:200] + "..." if len(integrated_statement) > 200 else integrated_statement
        print(f"\n{Colors.BLUE}Integrated statement preview:{Colors.END}")
        print(f"  {preview}\n")
        
        return True

def main():
    """Run the complete synthesis flow test"""
    # Check server health
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=2)
        if response.status_code != 200:
            print_error("API server is not healthy")
            sys.exit(1)
    except requests.exceptions.ConnectionError:
        print_error("API server is not running")
        print("Start with: poetry run uvicorn query_refinement_module.api.main:app --reload")
        sys.exit(1)
    
    print_section("SYNTHESIS FLOW TEST")
    print("Testing complete refinement workflow with synthesis result validation\n")
    
    # Authenticate
    token = register_and_login()
    
    # Start refinement
    start_result = start_refinement(token)
    query_id = start_result["query_id"]
    
    # Skip to synthesis using /submit command
    print_section("3. Completing Refinement")
    print("Using /submit command to complete all aspects and trigger synthesis...")
    
    response = submit_command(token, query_id, "/submit")
    
    if response.get('synthesis_ready'):
        print_success("Workflow marked as ready for synthesis")
    else:
        print_warning("Workflow not yet ready, checking status...")
        
        # Check if ready
        is_ready = check_ready_for_synthesis(token, query_id)
        if not is_ready:
            print_error("Workflow not ready for synthesis after /submit")
            print("This might indicate an issue with the /submit command")
            sys.exit(1)
    
    # Synthesize
    synthesis_result = synthesize_query(token, query_id)
    
    if not synthesis_result:
        print_error("Failed to get synthesis result")
        sys.exit(1)
    
    # Validate
    is_valid = validate_synthesis_result(synthesis_result)
    
    # Final verdict
    print_section("TEST RESULT")
    if is_valid:
        print(f"{Colors.GREEN}{Colors.BOLD}✅ TEST PASSED{Colors.END}")
        print("Synthesis result is properly formed and would display correctly in the frontend.")
    else:
        print(f"{Colors.RED}{Colors.BOLD}❌ TEST FAILED{Colors.END}")
        print("Synthesis result has issues that would prevent proper display in the frontend.")
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
