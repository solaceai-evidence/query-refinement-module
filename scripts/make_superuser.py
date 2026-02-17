#!/usr/bin/env python3
"""
Make a user a superuser (unlimited workflows).
Usage: poetry run python scripts/make_superuser.py <username>
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from query_refinement_module.db.session import SessionLocal
from query_refinement_module.db.models.user import User
from query_refinement_module.api.config import get_settings


def make_superuser(username: str):
    """Grant superuser status to a user."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"User '{username}' not found")
            return False
        
        if user.is_superuser:
            print(f"User '{username}' is already a superuser")
            return True
        
        user.is_superuser = True
        db.commit()

        settings = get_settings()
        if settings.enforce_workflow_limit:
            print(f"User '{username}' is now a superuser with unlimited workflows")
        else:
            print(f"User '{username}' is now a superuser")
        return True
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: poetry run python scripts/make_superuser.py <username>")
        sys.exit(1)
    
    username = sys.argv[1]
    success = make_superuser(username)
    sys.exit(0 if success else 1)
