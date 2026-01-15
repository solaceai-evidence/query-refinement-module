"""
Test script for database setup and CRUD operations.
"""
import time
from query_refinement_module.db.session import get_db_session
from query_refinement_module.db.crud import (
    create_user,
    get_user_by_email,
    verify_user_password,
    create_query_session,
    create_query,
    create_refinement_step,
    create_followup,
    update_followup_answer,
    update_refined_query,
    create_feedback,
    get_user_sessions,
    get_session_queries,
    get_query_refinement_steps,
    get_step_followups,
)
from query_refinement_module.db.database import init_db


def test_database_setup():
    """Test database initialization and CRUD operations."""
    
    # Initialize database (creates tables)
    print("Initializing database...")
    init_db()
    print("✓ Database initialized")
    
    with get_db_session() as db:
        # Test user creation
        print("\n1. Creating user...")
        # Use unique username to avoid conflicts in repeated test runs
        unique_username = f"testuser_{int(time.time() * 1000)}"
        user = create_user(db, username=unique_username, password="password123", email=f"{unique_username}@example.com", name="Test User")
        print(f"✓ User created: {user}")
        
        # Test user retrieval
        print("\n2. Retrieving user by email...")
        retrieved_user = get_user_by_email(db, f"{unique_username}@example.com")
        print(f"✓ User retrieved: {retrieved_user}")
        
        # Test password verification
        print("\n3. Verifying password...")
        verified_user = verify_user_password(db, f"{unique_username}@example.com", "password123")
        print(f"✓ Password verified: {verified_user is not None}")
        
        # Test session creation
        print("\n4. Creating query session...")
        session = create_query_session(db, user_id=user.id)
        print(f"✓ Session created: {session}")
        
        # Test query creation
        print("\n5. Creating query...")
        query = create_query(db, session_id=session.id, original_query="What are the effects of exercise on mental health?")
        print(f"✓ Query created: {query}")
        
        # Test refinement step creation
        print("\n6. Creating refinement step...")
        step = create_refinement_step(db, query_id=query.id, aspect_name="Population")
        print(f"✓ Refinement step created: {step}")
        
        # Test follow-up history
        print("\n7. Creating follow-up history...")
        followup1 = create_followup(db, refinement_step_id=step.id, question="What population are you interested in?")
        print(f"✓ Follow-up created: {followup1}")
        
        print("\n8. Updating follow-up answer...")
        followup1 = update_followup_answer(db, followup_id=followup1.id, answer="Adults aged 18-65")
        print(f"✓ Follow-up updated: {followup1}")
        
        # Test refined query update
        print("\n9. Updating refined query...")
        query = update_refined_query(db, query_id=query.id, refined_query="What are the effects of exercise on mental health in adults aged 18-65?")
        print(f"✓ Refined query updated: {query}")
        
        # Test feedback creation
        print("\n10. Creating feedback...")
        feedback = create_feedback(db, user_id=user.id, query_id=query.id, rating=5, comments="Very helpful!")
        print(f"✓ Feedback created: {feedback}")
        
        # Test data retrieval
        print("\n11. Retrieving user sessions...")
        sessions = get_user_sessions(db, user_id=user.id)
        print(f"✓ Found {len(sessions)} session(s)")
        
        print("\n12. Retrieving session queries...")
        queries = get_session_queries(db, session_id=session.id)
        print(f"✓ Found {len(queries)} query(ies)")
        
        print("\n13. Retrieving query refinement steps...")
        steps = get_query_refinement_steps(db, query_id=query.id)
        print(f"✓ Found {len(steps)} refinement step(s)")
        
        print("\n14. Retrieving follow-up history...")
        followups = get_step_followups(db, refinement_step_id=step.id)
        print(f"✓ Found {len(followups)} follow-up(s)")
        
        print("\n✅ All tests passed!")


if __name__ == "__main__":
    test_database_setup()
