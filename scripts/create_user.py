#!/usr/bin/env python3
"""Create a user and optionally grant superuser access.

Usage:
  poetry run python scripts/create_user.py --username alice --password "Secret123!" --email alice@example.com
  poetry run python scripts/create_user.py --username admin --superuser
"""
import argparse
import secrets
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from query_refinement_module.db.session import SessionLocal
from query_refinement_module.db.crud import create_user, get_user_by_username, get_user_by_email


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a user account")
    parser.add_argument("--username", required=True, help="Username for the new account")
    parser.add_argument("--password", help="Password (auto-generated if omitted)")
    parser.add_argument("--email", help="Optional email address")
    parser.add_argument("--name", help="Optional display name")
    parser.add_argument("--superuser", action="store_true", help="Grant superuser access")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    try:
        existing = get_user_by_username(db, args.username)
        if existing:
            if args.superuser and not existing.is_superuser:
                existing.is_superuser = True
                db.commit()
                print(f"✓ User '{args.username}' promoted to superuser")
            else:
                print(f"✓ User '{args.username}' already exists")
            return 0

        if args.email:
            email_owner = get_user_by_email(db, args.email)
            if email_owner:
                print(f"❌ Email '{args.email}' is already in use")
                return 1

        password = args.password or secrets.token_urlsafe(12)
        user = create_user(
            db,
            username=args.username,
            password=password,
            email=args.email,
            name=args.name,
        )

        if args.superuser:
            user.is_superuser = True
            db.commit()

        print(f"✓ Created user '{user.username}' (id={user.id})")
        print(f"  Password: {password}")
        if args.superuser:
            print("  Superuser: yes")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"❌ Error: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
