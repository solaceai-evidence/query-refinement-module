#!/usr/bin/env python3
"""
Quick test to verify workflow limits implementation.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from query_refinement_module.db.session import SessionLocal
from query_refinement_module.db.models.user import User
from query_refinement_module.db.models.query import Query


def test_implementation():
    """Verify database schema changes."""
    db = SessionLocal()
    try:
        print("Testing Workflow Limits Implementation\\n")
        print("=" * 50)
        
        # Test 1: Check User model has new fields
        print("\\n1. Checking User model...")
        user = db.query(User).first()
        if user:
            assert hasattr(user, 'is_superuser'), "Missing is_superuser field"
            assert hasattr(user, 'has_completed_workflow'), "Missing has_completed_workflow field"
            print(f"   ✓ User fields: is_superuser={user.is_superuser}, has_completed_workflow={user.has_completed_workflow}")
        else:
            print("   ⚠ No users in database yet")
        
        # Test 2: Check Query model has new fields
        print("\\n2. Checking Query model...")
        query = db.query(Query).first()
        if query:
            assert hasattr(query, 'consent_given'), "Missing consent_given field"
            assert hasattr(query, 'consent_given_at'), "Missing consent_given_at field"
            print(f"   ✓ Query fields: consent_given={query.consent_given}, consent_given_at={query.consent_given_at}")
        else:
            print("   ⚠ No queries in database yet")
        
        # Test 3: Count users by type
        print("\\n3. User Statistics...")
        total_users = db.query(User).count()
        superusers = db.query(User).filter(User.is_superuser == True).count()
        completed = db.query(User).filter(User.has_completed_workflow == True).count()
        print(f"   Total users: {total_users}")
        print(f"   Superusers: {superusers}")
        print(f"   Completed workflows: {completed}")
        
        # Test 4: Count queries by consent
        print("\\n4. Query Statistics...")
        total_queries = db.query(Query).count()
        consented = db.query(Query).filter(Query.consent_given == True).count()
        unconsented = db.query(Query).filter(Query.consent_given == False).count()
        print(f"   Total queries: {total_queries}")
        print(f"   Consented: {consented}")
        print(f"   Unconsented: {unconsented}")
        
        print("\\n" + "=" * 50)
        print("✓ All tests passed!")
        print("\\nImplementation is ready to use.")
        print("\\nNext step: Make yourself superuser with:")
        print("  poetry run python scripts/make_superuser.py <your_username>")
        
    except AssertionError as e:
        print(f"\\n❌ Test failed: {e}")
        return False
    except Exception as e:
        print(f"\\n❌ Error: {e}")
        return False
    finally:
        db.close()
    
    return True


if __name__ == "__main__":
    success = test_implementation()
    sys.exit(0 if success else 1)
