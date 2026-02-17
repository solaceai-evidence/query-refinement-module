#!/usr/bin/env python3
"""Create a user and optionally grant superuser access.

Usage:
  poetry run python scripts/create_user.py --username alice --password "Secret123!" --email alice@example.com
  poetry run python scripts/create_user.py --username admin --superuser
    poetry run python scripts/create_user.py --username bob --framework pico_advanced --framework eclipse
"""
import argparse
import secrets
import sys
from pathlib import Path
from typing import cast

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from query_refinement_module.db.session import SessionLocal
from query_refinement_module.db.crud import (
    assign_user_framework_access,
    create_user,
    get_user_by_email,
    get_user_by_username,
    get_user_framework_names,
)
from query_refinement_module.schema.registry import list_frameworks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a user account")
    parser.add_argument("--username", required=True, help="Username for the new account")
    parser.add_argument("--password", help="Password (auto-generated if omitted)")
    parser.add_argument("--email", help="Optional email address")
    parser.add_argument("--name", help="Optional display name")
    parser.add_argument("--superuser", action="store_true", help="Grant superuser access")
    parser.add_argument(
        "--framework",
        action="append",
        default=[],
        help="Assign framework access (repeatable)",
    )
    return parser.parse_args()


def _validate_frameworks(frameworks: list[str]) -> list[str]:
    available = set(list_frameworks())
    invalid = [name for name in frameworks if name not in available]
    if invalid:
        raise ValueError(
            f"Unknown framework(s): {', '.join(invalid)}. Available: {', '.join(sorted(available))}"
        )
    return frameworks


def main() -> int:
    args = parse_args()
    requested_frameworks = _validate_frameworks(args.framework)

    db = SessionLocal()
    try:
        existing = get_user_by_username(db, args.username)
        if existing:
            existing_id = cast(int, existing.id)
            if args.superuser and not bool(existing.is_superuser):
                setattr(existing, "is_superuser", True)
                db.commit()
                print(f"User '{args.username}' promoted to superuser")
            else:
                print(f"User '{args.username}' already exists")

            for framework_name in requested_frameworks:
                assign_user_framework_access(db, user_id=existing_id, framework_name=framework_name)

            if requested_frameworks:
                assigned = sorted(get_user_framework_names(db, existing_id))
                print(f"Framework access: {', '.join(assigned)}")
            return 0

        if args.email:
            email_owner = get_user_by_email(db, args.email)
            if email_owner:
                print(f"Error: Email '{args.email}' is already in use")
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
            setattr(user, "is_superuser", True)
            db.commit()

        user_id = cast(int, user.id)

        for framework_name in requested_frameworks:
            assign_user_framework_access(db, user_id=user_id, framework_name=framework_name)

        assigned = sorted(get_user_framework_names(db, user_id))

        print(f"Created user '{user.username}' (id={user.id})")
        print(f"  Password: {password}")
        if bool(user.is_superuser):
            print("  Superuser: yes")
        if assigned:
            print(f"  Framework access: {', '.join(assigned)}")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"Error: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
