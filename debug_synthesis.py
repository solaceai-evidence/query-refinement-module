#!/usr/bin/env python3
"""Debug script to check synthesis status for recent sessions."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker
from query_refinement_module.db.models.query import Query
from query_refinement_module.db.models.query_session import QuerySession
from query_refinement_module.db.models.user import User
from query_refinement_module.db.database import DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def check_recent_sessions(limit=5):
    """Check the most recent sessions and their synthesis status."""
    db = SessionLocal()
    try:
        print("=" * 80)
        print("RECENT SESSIONS AND SYNTHESIS STATUS")
        print("=" * 80)
        
        # Get recent queries
        queries = db.query(Query).join(QuerySession).order_by(desc(Query.created_at)).limit(limit).all()
        
        if not queries:
            print("\n❌ No queries found in database")
            return
        
        for i, query in enumerate(queries, 1):
            print(f"\n{i}. Query ID: {query.id}")
            print(f"   Session ID: {query.session_id}")
            print(f"   Created: {query.created_at}")
            print(f"   Original Query: {query.original_query[:100]}...")
            print(f"   Framework: {query.session.framework_name}")
            
            # Check if refined query exists
            if query.refined_query:
                print(f"   ✅ HAS REFINED QUERY")
                print(f"   Refined Query Length: {len(query.refined_query)}")
                print(f"   Refined Query Preview: {query.refined_query[:200]}...")
            else:
                print(f"   ❌ NO REFINED QUERY (synthesis not completed or empty)")
            
            # Check refinement steps
            step_count = len(query.refinement_steps)
            print(f"   Refinement Steps: {step_count}")
            
            if step_count > 0:
                complete_count = sum(1 for step in query.refinement_steps if step.is_complete)
                print(f"   Complete Steps: {complete_count}/{step_count}")
                
                # Show step details
                for step in query.refinement_steps:
                    status = "✅" if step.is_complete else "⏳"
                    followup_count = len(step.followup_history) if step.followup_history else 0
                    print(f"     {status} {step.aspect_name}: {followup_count} interactions")
            
            print(f"   User ID: {query.session.user_id}")
            
        print("\n" + "=" * 80)
        
        # Check the most recent query in detail
        if queries:
            latest = queries[0]
            print(f"\nMOST RECENT QUERY (ID: {latest.id}) DETAILS:")
            print(f"  Session exists: Yes")
            print(f"  Framework: {latest.session.framework_name}")
            print(f"  All steps complete: {all(step.is_complete for step in latest.refinement_steps) if latest.refinement_steps else 'No steps'}")
            print(f"  Has refined query: {'Yes' if latest.refined_query else 'No'}")
            
            if not latest.refined_query and latest.refinement_steps:
                if all(step.is_complete for step in latest.refinement_steps):
                    print("\n⚠️  WARNING: All steps complete but NO refined query!")
                    print("   This suggests synthesis was never called or failed.")
                    print("\n   To manually trigger synthesis from the frontend:")
                    print(f"   1. Open browser console")
                    print(f"   2. Run: localStorage.getItem('refinement_session')")
                    print(f"   3. Check if queryId matches: {latest.id}")
                    print(f"   4. Click any 'Finish' or 'Synthesize' button again")
                else:
                    incomplete = [s.aspect_name for s in latest.refinement_steps if not s.is_complete]
                    print(f"\n   ⏳ Incomplete aspects: {', '.join(incomplete)}")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    check_recent_sessions(limit=3)
