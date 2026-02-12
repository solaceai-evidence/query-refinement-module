#!/usr/bin/env python3
"""Import username/password pairs into the database."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List

from query_refinement_module.db.database import SessionLocal
from query_refinement_module.db import crud


def _infer_format(path: Path, explicit: str | None) -> str:
    if explicit:
        return explicit.lower()
    if path.suffix.lower() == ".csv":
        return "csv"
    return "json"


def load_json(path: Path) -> List[Dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("JSON must be a list of objects")
    return data


def load_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [row for row in reader]


def iter_records(path: Path, fmt: str) -> Iterable[Dict[str, str]]:
    if fmt == "csv":
        return load_csv(path)
    return load_json(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import credentials into the database")
    parser.add_argument("--input", type=Path, required=True, help="Input file path (.json or .csv)")
    parser.add_argument("--format", choices=["json", "csv"], help="Input format (defaults by file extension)")
    parser.add_argument("--on-duplicate", choices=["skip", "fail"], default="skip", help="Duplicate username handling")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing to the database")
    return parser.parse_args()


def validate_password_strength(password: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if len(password) > 128:
        raise ValueError("Password must be at most 128 characters long")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"[0-9]", password):
        raise ValueError("Password must contain at least one digit")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        raise ValueError("Password must contain at least one special character")


def normalize_record(record: Dict[str, str]) -> Dict[str, str]:
    username = (record.get("username") or "").strip()
    password = record.get("password") or ""
    email = (record.get("email") or "").strip() or None
    name = (record.get("name") or "").strip() or None

    if not username:
        raise ValueError("Record missing username")
    if not password:
        raise ValueError(f"Record missing password for username '{username}'")
    validate_password_strength(password)

    normalized: Dict[str, str] = {
        "username": username,
        "password": password,
    }
    if email:
        normalized["email"] = email
    if name:
        normalized["name"] = name
    return normalized


def main() -> None:
    args = parse_args()
    input_path = args.input
    input_format = _infer_format(input_path, args.format)

    records = [normalize_record(record) for record in iter_records(input_path, input_format)]

    if args.dry_run:
        print(f"Validated {len(records)} records (dry run)")
        return

    session = SessionLocal()
    created = 0
    skipped = 0
    try:
        for record in records:
            existing = crud.get_user_by_username(session, record["username"])
            if existing:
                if args.on_duplicate == "fail":
                    raise ValueError(f"Duplicate username: {record['username']}")
                skipped += 1
                continue

            crud.create_user(
                session,
                username=record["username"],
                password=record["password"],
                email=record.get("email"),
                name=record.get("name"),
            )
            created += 1
    finally:
        session.close()

    print(f"Created {created} users; skipped {skipped} duplicates")


if __name__ == "__main__":
    main()
