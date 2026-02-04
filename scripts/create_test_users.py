#!/usr/bin/env python3
"""
Create test users for load testing.

Usage:
    poetry run python scripts/create_test_users.py
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from query_refinement_module.db.database import SessionLocal, engine, Base
from query_refinement_module.db.models.user import User
from query_refinement_module.api.auth import get_password_hash

# Create tables
Base.metadata.create_all(bind=engine)

def create_test_user(db: Session, username: str, email: str, password: str, name: str = None):
    """Create a test user if it doesn't exist."""
    # Check if user already exists
    existing_user = db.query(User).filter(
        (User.username == username) | (User.email == email)
    ).first()
    
    if existing_user:
        print(f"✓ User '{username}' already exists")
        return existing_user
    
    # Create new user
    hashed_password = get_password_hash(password)
    user = User(
        username=username,
        email=email,
        password_hash=hashed_password,
        name=name,
        is_superuser=False,
        has_completed_workflow=False
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    print(f"✓ Created user '{username}' (email: {email})")
    return user


def main():
    """Create test users for load testing."""
    db = SessionLocal()
    
    try:
        print("Creating test users for load testing...\n")
        
        # Create test user for locust
        create_test_user(
            db=db,
            username="test_user_001",
            email="test_user_001@example.com",
            password="testpass123",
            name="Test User 001"
        )
        
        # Create additional test users
        for i in range(2, 11):
            create_test_user(
                db=db,
                username=f"test_user_{i:03d}",
                email=f"test_user_{i:03d}@example.com",
                password="testpass123",
                name=f"Test User {i:03d}"
            )
        
        print(f"\n✅ Successfully created/verified 10 test users")
        print(f"\nCredentials for load testing:")
        print(f"  Username: test_user_001")
        print(f"  Password: testpass123")
        print(f"\nYou can now run locust:")
        print(f"  poetry run locust -f tests/load/locustfile.py --host=http://localhost:8000")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
