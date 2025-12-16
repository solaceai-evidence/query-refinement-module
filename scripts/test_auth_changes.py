#!/usr/bin/env python
"""
Test script for dual authentication (username and email).
"""
import requests
import json

BASE_URL = "http://localhost:8000/api"

def test_registration():
    """Test user registration with username."""
    print("=" * 60)
    print("TEST 1: Register with username only (no email)")
    print("=" * 60)
    
    response = requests.post(
        f"{BASE_URL}/auth/register",
        json={
            "username": "johndoe",
            "password": "SecurePass123!",
            "name": "John Doe"
        }
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()
    
    print("=" * 60)
    print("TEST 2: Register with username and email")
    print("=" * 60)
    
    response = requests.post(
        f"{BASE_URL}/auth/register",
        json={
            "username": "janedoe",
            "email": "jane@example.com",
            "password": "SecurePass456!",
            "name": "Jane Doe"
        }
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()


def test_login():
    """Test login with both username and email."""
    print("=" * 60)
    print("TEST 3: Login with username")
    print("=" * 60)
    
    response = requests.post(
        f"{BASE_URL}/auth/login",
        data={
            "username": "johndoe",
            "password": "SecurePass123!"
        }
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 200:
        token = response.json()["access_token"]
        print("\n--- Testing /me endpoint with token ---")
        me_response = requests.get(
            f"{BASE_URL}/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        print(f"Status: {me_response.status_code}")
        print(f"Response: {json.dumps(me_response.json(), indent=2)}")
    print()
    
    print("=" * 60)
    print("TEST 4: Login with email (for user with email)")
    print("=" * 60)
    
    response = requests.post(
        f"{BASE_URL}/auth/login",
        data={
            "username": "jane@example.com",  # OAuth2 field name
            "password": "SecurePass456!"
        }
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 200:
        token = response.json()["access_token"]
        print("\n--- Testing /me endpoint with token ---")
        me_response = requests.get(
            f"{BASE_URL}/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        print(f"Status: {me_response.status_code}")
        print(f"Response: {json.dumps(me_response.json(), indent=2)}")
    print()


def test_validation():
    """Test validation errors."""
    print("=" * 60)
    print("TEST 5: Invalid username (special characters)")
    print("=" * 60)
    
    response = requests.post(
        f"{BASE_URL}/auth/register",
        json={
            "username": "user@name!",
            "password": "SecurePass123!",
        }
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()
    
    print("=" * 60)
    print("TEST 6: Duplicate username")
    print("=" * 60)
    
    response = requests.post(
        f"{BASE_URL}/auth/register",
        json={
            "username": "johndoe",  # Already exists
            "password": "SecurePass789!",
        }
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()


if __name__ == "__main__":
    print("\n🚀 Starting Authentication Tests")
    print(f"Base URL: {BASE_URL}\n")
    
    try:
        # Check if server is running
        response = requests.get(f"http://localhost:8000/health", timeout=2)
        if response.status_code != 200:
            print("❌ Server is not responding correctly")
            exit(1)
    except requests.exceptions.ConnectionError:
        print("❌ Server is not running. Please start it with:")
        print("   uvicorn query_refinement_module.api.main:app --reload")
        exit(1)
    
    test_registration()
    test_login()
    test_validation()
    
    print("\n✅ All tests completed!")
