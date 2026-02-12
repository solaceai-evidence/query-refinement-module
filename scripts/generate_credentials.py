#!/usr/bin/env python3
"""Generate username/password pairs and export to JSON or CSV."""

from __future__ import annotations

import argparse
import csv
import json
import secrets
import string
from pathlib import Path
from typing import List, Dict


def _infer_format(path: Path, explicit: str | None) -> str:
    if explicit:
        return explicit.lower()
    if path.suffix.lower() == ".csv":
        return "csv"
    return "json"


_SPECIAL_CHARS = "!@#$%^&*(),.?\":{}|<>"


def _generate_password(length: int) -> str:
    if length < 8 or length > 128:
        raise ValueError("Password length must be between 8 and 128 characters")

    required = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(_SPECIAL_CHARS),
    ]

    remaining = length - len(required)
    alphabet = string.ascii_letters + string.digits + _SPECIAL_CHARS
    required.extend(secrets.choice(alphabet) for _ in range(remaining))
    secrets.SystemRandom().shuffle(required)
    return "".join(required)


def _build_username(prefix: str, index: int, pad_width: int) -> str:
    if pad_width > 0:
        return f"{prefix}{index:0{pad_width}d}"
    return f"{prefix}{index}"


def generate_records(count: int, prefix: str, start_index: int, pad_width: int, password_length: int) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    for offset in range(count):
        index = start_index + offset
        username = _build_username(prefix, index, pad_width)
        records.append({
            "username": username,
            "password": _generate_password(password_length),
        })
    return records


def write_json(path: Path, records: List[Dict[str, str]]) -> None:
    path.write_text(json.dumps(records, indent=2), encoding="utf-8")


def write_csv(path: Path, records: List[Dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["username", "password"])
        writer.writeheader()
        writer.writerows(records)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate username/password pairs")
    parser.add_argument("--count", type=int, required=True, help="Number of credentials to generate")
    parser.add_argument("--output", type=Path, help="Primary output path (.json or .csv)")
    parser.add_argument("--format", choices=["json", "csv"], help="Primary output format (defaults by file extension)")
    parser.add_argument("--output-json", type=Path, help="Optional JSON output path")
    parser.add_argument("--output-csv", type=Path, help="Optional CSV output path")
    parser.add_argument("--username-prefix", default="user", help="Username prefix, e.g. user")
    parser.add_argument("--start-index", type=int, default=1, help="Starting numeric index")
    parser.add_argument("--pad-width", type=int, default=3, help="Zero padding width (0 disables padding)")
    parser.add_argument("--password-length", type=int, default=16, help="Password length")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = args.output
    output_format = _infer_format(output_path, args.format) if output_path else None

    records = generate_records(
        count=args.count,
        prefix=args.username_prefix,
        start_index=args.start_index,
        pad_width=args.pad_width,
        password_length=args.password_length,
    )

    written: List[Path] = []
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_format == "csv":
            write_csv(output_path, records)
        else:
            write_json(output_path, records)
        written.append(output_path)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.output_json, records)
        written.append(args.output_json)

    if args.output_csv:
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        write_csv(args.output_csv, records)
        written.append(args.output_csv)

    if not written:
        raise SystemExit("Provide --output, --output-json, or --output-csv")

    joined = ", ".join(str(path) for path in written)
    print(f"Wrote {len(records)} credentials to {joined}")


if __name__ == "__main__":
    main()
