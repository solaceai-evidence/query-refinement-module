#!/usr/bin/env python3
"""Quick test to verify API is responding correctly after changes"""
import requests
import time
import random

BASE_URL = "http://localhost:8000"

def quick_test():
    # Register and login
    username = f"quicktest_{random.randint(100000, 999999)}"
    
    print("1. Registering...")
    reg_response = requests.post(f"{BASE_URL}/api/auth/register", json={"username": username, "password": "testpassword123"})
    print(f"   Registration: {reg_response.status_code} - {reg_response.text[:100]}")
    
    print("2. Logging in...")
    response = requests.post(f"{BASE_URL}/api/auth/login", data={"username": username, "password": "testpassword123"})
    if response.status_code != 200:
        print(f"Login failed: {response.status_code} - {response.text}")
        return
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    print("3. Starting refinement...")
    response = requests.post(
        f"{BASE_URL}/api/refinement/start",
        json={"framework_name": "mph_dissertation", "original_query": "I want to study childhood obesity in urban areas"},
        headers=headers
    )
    data = response.json()
    query_id = data["query_id"]
    print(f"   Query ID: {query_id}")
    print(f"   Next question: {data.get('next_prompt', {}).get('question', 'NO QUESTION')[:100]}")
    
    print("\n4. Submitting answer...")
    response = requests.post(
        f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
        json={"answer": "I want to examine risk factors for obesity in children"},
        headers=headers
    )
    data = response.json()
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        question = data.get("next_prompt", {}).get("question")
        if question:
            print(f"   ✅ SUCCESS! Got next question: {question[:100]}...")
        else:
            print(f"   ❌ FAILED! No question in response: {data}")
    else:
        print(f"   ❌ ERROR! Response: {data}")

if __name__ == "__main__":
    quick_test()
