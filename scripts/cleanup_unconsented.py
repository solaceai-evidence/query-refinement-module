#!/usr/bin/env python3
"""
Cleanup script to remove unconsented queries and associated data.
Removes queries older than specified days without consent (no feedback submitted).

Usage: poetry run python scripts/cleanup_unconsented.py [--days 7] [--dry-run]
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from query_refinement_module.db.session import SessionLocal
from query_refinement_module.db.models.query import Query


def cleanup_unconsented_data(days_old: int = 7, dry_run: bool = False):
    """Delete queries without consent older than specified days."""
    db = SessionLocal()
    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
        
        # Find unconsented queries older than cutoff
        old_unconsented = db.query(Query).filter(
            Query.consent_given == False,
            Query.created_at < cutoff_date
        ).all()
        
        print(f"{'[DRY RUN] ' if dry_run else ''}Found {len(old_unconsented)} unconsented queries older than {days_old} days")
        
        if not old_unconsented:
            print("Nothing to clean up.")
            return
        
        for query in old_unconsented:
            print(f"  Query {query.id}: created {query.created_at}, session {query.session_id}")
        
        if dry_run:
            print(f"\\n[DRY RUN] Would delete {len(old_unconsented)} queries")
            print("Run without --dry-run to actually delete")
        else:
            for query in old_unconsented:
                db.delete(query)
            
            db.commit()
            print(f"\\n✓ Cleanup complete. Deleted {len(old_unconsented)} unconsented queries.")
        
    except Exception as e:
        print(f"❌ Error during cleanup: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cleanup unconsented query data")
    parser.add_argument('--days', type=int, default=7, help='Remove data older than N days (default: 7)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without deleting')
    
    args = parser.parse_args()
    
    print(f"Cleanup Configuration:")
    print(f"  Days threshold: {args.days}")
    print(f"  Mode: {'DRY RUN' if args.dry_run else 'LIVE'}\\n")
    
    cleanup_unconsented_data(days_old=args.days, dry_run=args.dry_run)
