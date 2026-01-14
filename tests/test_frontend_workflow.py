#!/usr/bin/env python3
"""
Test script to simulate the frontend workflow and debug API issues.
This helps identify backend problems without using the browser.
"""
import requests
import json
import sys

BASE_URL = "http://localhost:8000"

def print_section(title):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")

def print_response(response, show_body=True):
    print(f"Status: {response.status_code}")
    print(f"Headers: {dict(response.headers)}")
    if show_body:
        try:
            body = response.json()
            print(f"Body: {json.dumps(body, indent=2)}")
        except:
            print(f"Body (text): {response.text[:500]}")

def register_and_login():
    """Register and login to get auth token"""
    print_section("1. Authentication")
    
    # Register
    username = f"testuser_{int(time.time())}"
    register_data = {
        "username": username,
        "password": "TestPass123!"
    }
    
    print(f"Registering user: {username}")
    response = requests.post(f"{BASE_URL}/api/auth/register", json=register_data)
    print_response(response, show_body=False)
    
    if response.status_code not in [200, 201]:
        # Try login if user exists
        print("\nUser might exist, trying login...")
    
    # Login
    login_data = {
        "username": username,
        "password": "TestPass123!",
        "grant_type": "password"
    }
    
    print(f"\nLogging in...")
    response = requests.post(f"{BASE_URL}/api/auth/login", data=login_data)
    print_response(response)
    
    if response.status_code != 200:
        print("❌ Login failed")
        sys.exit(1)
    
    token = response.json()["access_token"]
    print(f"✓ Got token: {token[:20]}...")
    return token

def test_workflow(token):
    """Test the complete refinement workflow"""
    headers = {"Authorization": f"Bearer {token}"}
    
    # Step 1: Get frameworks
    print_section("2. Get Available Frameworks")
    response = requests.get(f"{BASE_URL}/api/refinement/frameworks", headers=headers)
    print_response(response)
    
    if response.status_code != 200:
        print("❌ Failed to get frameworks")
        return
    
    frameworks = response.json()
    framework_names = frameworks.get('frameworks', [])
    print(f"✓ Available frameworks: {framework_names}")
    
    # Step 2: Start refinement
    print_section("3. Start Refinement")
    start_data = {
        "framework_name": "mph_dissertation",
        "original_query": "I want to study childhood obesity in urban areas"
    }
    
    print(f"Starting refinement with: {start_data}")
    response = requests.post(f"{BASE_URL}/api/refinement/start", json=start_data, headers=headers)
    print_response(response)
    
    if response.status_code != 201:
        print("❌ Failed to start refinement")
        return
    
    data = response.json()
    query_id = data["query_id"]
    session_id = data["session_id"]
    next_prompt = data.get("next_prompt")
    
    print(f"\n✓ Query ID: {query_id}")
    print(f"✓ Session ID: {session_id}")
    print(f"✓ Next prompt present: {next_prompt is not None}")
    
    if next_prompt:
        print(f"\nNext prompt details:")
        print(f"  - aspect_id: {next_prompt.get('aspect_id')}")
        print(f"  - aspect_name: {next_prompt.get('aspect_name')}")
        print(f"  - question: {next_prompt.get('question')}")
        print(f"  - description: {next_prompt.get('description')[:100]}..." if next_prompt.get('description') else "  - description: None")
    
    # Step 3: Submit first answer
    print_section("4. Submit First Answer")
    answer_data = {
        "answer": "I want to focus on children aged 5-12 in low-income neighborhoods"
    }
    
    print(f"Submitting answer: {answer_data['answer']}")
    response = requests.post(
        f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
        json=answer_data,
        headers=headers
    )
    print_response(response)
    
    if response.status_code != 200:
        print("❌ Failed to submit answer")
        return
    
    data = response.json()
    print(f"\n✓ Response type: {'CommandResponse' if 'command_type' in data else 'SubmitAnswerResponse'}")
    
    next_prompt = data.get("next_prompt")
    print(f"✓ Next prompt present: {next_prompt is not None}")
    
    if next_prompt:
        print(f"\nNext prompt details:")
        print(f"  - aspect_id: {next_prompt.get('aspect_id')}")
        print(f"  - aspect_name: {next_prompt.get('aspect_name')}")
        print(f"  - question: {next_prompt.get('question')}")
        print(f"  - question is None: {next_prompt.get('question') is None}")
        print(f"  - question is empty: {next_prompt.get('question') == ''}")
        
        if not next_prompt.get('question'):
            print("\n⚠️  WARNING: question field is None or empty!")
            print("   This will cause the frontend to not render anything!")
    
    # Step 4: Get status
    print_section("5. Get Status")
    response = requests.get(f"{BASE_URL}/api/refinement/queries/{query_id}/status", headers=headers)
    print_response(response)
    
    if response.status_code == 200:
        status = response.json()
        print(f"\n✓ Current aspect: {status.get('current_aspect')}")
        aspects_summary = status.get('aspects_summary', {})
        print(f"✓ Total aspects: {aspects_summary.get('total_aspects')}")
        print(f"✓ Completed: {aspects_summary.get('completed_steps')}")
        print(f"✓ Pending: {aspects_summary.get('pending_steps')}")
    
    # Step 5: Test a command
    print_section("6. Test Command (/status)")
    command_data = {"answer": "/status"}
    
    response = requests.post(
        f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
        json=command_data,
        headers=headers
    )
    print_response(response)
    
    if response.status_code == 200:
        data = response.json()
        if data.get('command_type'):
            print(f"\n✓ Command executed: {data['command_type']}")
            print(f"✓ Message: {data.get('message')}")

if __name__ == "__main__":
    import time
    
    try:
        token = register_and_login()
        test_workflow(token)
        
        print_section("✅ Test Complete")
        print("Review the output above to identify any issues.")
        
    except Exception as e:
        print_section("❌ Test Failed")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
