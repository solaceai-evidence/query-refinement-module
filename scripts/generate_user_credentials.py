#!/usr/bin/env python3
"""
Generate and create user credentials for controlled access.

Usage:
    # Generate credentials for 50 users and save to JSON file
    poetry run python scripts/generate_user_credentials.py --generate 50 --output credentials.json
    
    # Generate credentials and save to CSV (for Excel)
    poetry run python scripts/generate_user_credentials.py --generate 50 --output credentials.csv --format csv
    
    # Create users from saved credentials (auto-detects format)
    poetry run python scripts/generate_user_credentials.py --create-from credentials.csv
    
    # Generate and create in one step (without email)
    poetry run python scripts/generate_user_credentials.py --generate 50 --create-now
    
    # Generate and create with email addresses
    poetry run python scripts/generate_user_credentials.py --generate 50 --create-now --with-email
"""
import sys
import os
import secrets
import string
import json
import csv
from pathlib import Path
from typing import List, Tuple, Dict

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from query_refinement_module.db.database import SessionLocal, engine, Base
from query_refinement_module.db.models.user import User
from query_refinement_module.api.auth import get_password_hash


def generate_secure_password(length: int = 16) -> str:
    """
    Generate a secure random password.
    
    Password contains:
    - Uppercase letters
    - Lowercase letters
    - Digits
    - Special characters
    
    Args:
        length: Length of the password (default: 16)
    
    Returns:
        A secure random password
    """
    # Define character sets
    uppercase = string.ascii_uppercase
    lowercase = string.ascii_lowercase
    digits = string.digits
    special = "!@#$%^&*"
    
    # Ensure at least one character from each set
    password = [
        secrets.choice(uppercase),
        secrets.choice(lowercase),
        secrets.choice(digits),
        secrets.choice(special)
    ]
    
    # Fill the rest with random characters from all sets
    all_chars = uppercase + lowercase + digits + special
    password += [secrets.choice(all_chars) for _ in range(length - 4)]
    
    # Shuffle to randomize positions
    secrets.SystemRandom().shuffle(password)
    
    return ''.join(password)


def generate_user_credentials(n: int, starting_number: int = 1) -> List[Tuple[str, str]]:
    """
    Generate N pairs of (username, password).
    
    Usernames are in the format 'user_XXX' where XXX is a zero-padded number.
    Passwords are secure random strings.
    
    Args:
        n: Number of user credential pairs to generate
        starting_number: Starting number for username sequence (default: 1)
    
    Returns:
        List of tuples containing (username, password) pairs
    
    Example:
        >>> credentials = generate_user_credentials(5)
        >>> print(credentials[0])
        ('user_001', 'aB3$xY9...')
    """
    if n <= 0:
        raise ValueError("Number of users must be positive")
    
    if starting_number < 1:
        raise ValueError("Starting number must be at least 1")
    
    credentials = []
    used_passwords = set()
    
    for i in range(starting_number, starting_number + n):
        username = f"user_{i:03d}"
        
        # Generate unique password
        password = generate_secure_password()
        while password in used_passwords:
            password = generate_secure_password()
        
        used_passwords.add(password)
        credentials.append((username, password))
    
    return credentials


def create_users_in_db(credentials: List[Tuple[str, str]], db: Session = None, include_email: bool = False) -> Dict[str, any]:
    """
    Create users in the database from credential pairs.
    
    Args:
        credentials: List of (username, password) tuples
        db: Database session (optional, will create if not provided)
        include_email: Whether to include email addresses (default: False, since email is optional)
    
    Returns:
        Dictionary with statistics about created/skipped users
        {
            'created': int,
            'skipped': int,
            'failed': int,
            'details': List[Dict]
        }
    
    Example:
        >>> credentials = generate_user_credentials(5)
        >>> result = create_users_in_db(credentials)
        >>> print(f"Created {result['created']} users")
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    
    result = {
        'created': 0,
        'skipped': 0,
        'failed': 0,
        'details': []
    }
    
    try:
        for username, password in credentials:
            try:
                # Check if user already exists
                existing_user = db.query(User).filter(
                    User.username == username
                ).first()
                
                if existing_user:
                    result['skipped'] += 1
                    result['details'].append({
                        'username': username,
                        'status': 'skipped',
                        'reason': 'User already exists'
                    })
                    print(f"⊘ Skipped '{username}' (already exists)")
                    continue
                
                # Create new user (email is optional)
                hashed_password = get_password_hash(password)
                
                user = User(
                    username=username,
                    email=f"{username}@system.local" if include_email else None,
                    password_hash=hashed_password,
                    name=username.replace('_', ' ').title(),
                    is_superuser=False,
                    has_completed_workflow=False
                )
                
                db.add(user)
                db.commit()
                db.refresh(user)
                
                result['created'] += 1
                result['details'].append({
                    'username': username,
                    'status': 'created',
                    'user_id': user.id
                })
                print(f"✓ Created user '{username}'")
                
            except Exception as e:
                result['failed'] += 1
                result['details'].append({
                    'username': username,
                    'status': 'failed',
                    'error': str(e)
                })
                print(f"✗ Failed to create '{username}': {e}")
                db.rollback()
    
    finally:
        if close_db:
            db.close()
    
    return result


def save_credentials_to_file(credentials: List[Tuple[str, str]], filepath: str, format: str = 'json'):
    """
    Save credentials to a file in JSON or CSV format.
    
    Args:
        credentials: List of (username, password) tuples
        filepath: Path to output file
        format: Output format ('json' or 'csv')
    """
    if format.lower() == 'csv':
        save_credentials_to_csv(credentials, filepath)
    else:
        save_credentials_to_json(credentials, filepath)


def save_credentials_to_json(credentials: List[Tuple[str, str]], filepath: str):
    """
    Save credentials to a JSON file.
    
    Args:
        credentials: List of (username, password) tuples
        filepath: Path to output file
    """
    data = {
        'credentials': [
            {'username': username, 'password': password}
            for username, password in credentials
        ],
        'count': len(credentials),
        'format': 'json'
    }
    
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✓ Saved {len(credentials)} credentials to '{filepath}' (JSON format)")


def save_credentials_to_csv(credentials: List[Tuple[str, str]], filepath: str):
    """
    Save credentials to a CSV file (Excel-compatible).
    Email column omitted since it's optional in the system.
    
    Args:
        credentials: List of (username, password) tuples
        filepath: Path to output file
    """
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        # Write header
        writer.writerow(['Username', 'Password'])
        # Write credentials
        for username, password in credentials:
            writer.writerow([username, password])
    
    print(f"✓ Saved {len(credentials)} credentials to '{filepath}' (CSV format, Excel-compatible)")


def load_credentials_from_file(filepath: str) -> List[Tuple[str, str]]:
    """
    Load credentials from a JSON or CSV file (auto-detects format).
    
    Args:
        filepath: Path to input file
    
    Returns:
        List of (username, password) tuples
    """
    # Auto-detect format based on file extension
    if filepath.lower().endswith('.csv'):
        return load_credentials_from_csv(filepath)
    else:
        return load_credentials_from_json(filepath)


def load_credentials_from_json(filepath: str) -> List[Tuple[str, str]]:
    """
    Load credentials from a JSON file.
    
    Args:
        filepath: Path to input file
    
    Returns:
        List of (username, password) tuples
    """
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    credentials = [
        (cred['username'], cred['password'])
        for cred in data['credentials']
    ]
    
    print(f"✓ Loaded {len(credentials)} credentials from '{filepath}' (JSON format)")
    return credentials


def load_credentials_from_csv(filepath: str) -> List[Tuple[str, str]]:
    """
    Load credentials from a CSV file.
    
    Args:
        filepath: Path to input file
    
    Returns:
        List of (username, password) tuples
    """
    credentials = []
    
    with open(filepath, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            username = row['Username']
            password = row['Password']
            credentials.append((username, password))
    
    print(f"✓ Loaded {len(credentials)} credentials from '{filepath}' (CSV format)")
    return credentials


def print_credentials_table(credentials: List[Tuple[str, str]]):
    """Print credentials in a formatted table."""
    print("\n" + "="*70)
    print(f"{'Username':<20} | {'Password':<45}")
    print("="*70)
    for username, password in credentials:
        print(f"{username:<20} | {password:<45}")
    print("="*70 + "\n")


def main():
    """Main CLI handler."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Generate and create user credentials for controlled access'
    )
    parser.add_argument(
        '--generate', '-g',
        type=int,
        metavar='N',
        help='Generate N user credential pairs'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        metavar='FILE',
        help='Save generated credentials to file (.json or .csv)'
    )
    parser.add_argument(
        '--format', '-f',
        type=str,
        choices=['json', 'csv'],
        default='json',
        help='Output format: json (default) or csv (Excel-compatible)'
    )
    parser.add_argument(
        '--create-from', '-c',
        type=str,
        metavar='FILE',
        help='Create users from credentials file (auto-detects JSON or CSV)'
    )
    parser.add_argument(
        '--create-now',
        action='store_true',
        help='Create users immediately after generation'
    )
    parser.add_argument(
        '--starting-number', '-s',
        type=int,
        default=1,
        help='Starting number for username sequence (default: 1)'
    )
    parser.add_argument(
        '--print-table', '-p',
        action='store_true',
        help='Print credentials in a formatted table'
    )
    parser.add_argument(
        '--with-email',
        action='store_true',
        help='Include email addresses when creating users (default: False, email is optional)'
    )
    
    args = parser.parse_args()
    
    # Ensure database tables exist
    Base.metadata.create_all(bind=engine)
    
    # Generate credentials
    if args.generate:
        print(f"\nGenerating {args.generate} user credentials...")
        credentials = generate_user_credentials(args.generate, args.starting_number)
        print(f"✓ Generated {len(credentials)} credential pairs\n")
        
        if args.print_table:
            print_credentials_table(credentials)
        
        # Save to file if requested
        if args.output:
            save_credentials_to_file(credentials, args.output, args.format)
        
        # Create users if requested
        if args.create_now:
            print("\nCreating users in database...")
            result = create_users_in_db(credentials, include_email=args.with_email)
            print(f"\n✅ Summary:")
            print(f"   Created: {result['created']}")
            print(f"   Skipped: {result['skipped']}")
            print(f"   Failed:  {result['failed']}")
        
        # Print reminder if not creating now and not saving
        if not args.create_now and not args.output:
            print("⚠️  Credentials generated but not saved or created.")
            print("   Use --output to save or --create-now to create users.")
    
    # Create from file
    elif args.create_from:
        print(f"\nLoading credentials from '{args.create_from}'...")
        credentials = load_credentials_from_file(args.create_from)
        
        if args.print_table:
            print_credentials_table(credentials)
        
        print("\nCreating users in database...")
        result = create_users_in_db(credentials, include_email=args.with_email)
        print(f"\n✅ Summary:")
        print(f"   Created: {result['created']}")
        print(f"   Skipped: {result['skipped']}")
        print(f"   Failed:  {result['failed']}")
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
