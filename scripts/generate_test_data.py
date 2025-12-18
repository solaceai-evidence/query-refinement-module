"""
Test Data Generator for Load Testing

Creates realistic test data for load testing:
- Test users
- API keys
- Sample queries
- Schema configurations

Usage:
    # Generate data for development database
    poetry run python scripts/generate_test_data.py

    # Generate data with custom counts
    poetry run python scripts/generate_test_data.py --users 50 --keys-per-user 2

    # Clean up existing test data
    poetry run python scripts/generate_test_data.py --clean

    # Generate and export to file
    poetry run python scripts/generate_test_data.py --export test_data.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
from sqlalchemy import select
from passlib.context import CryptContext

from query_refinement_module.db.database import SessionLocal
from query_refinement_module.db.models.user import User

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ============================================================================
# Test Data Templates
# ============================================================================

# Standard password for all test users
TEST_PASSWORD = "testpass123"

SAMPLE_USERS = [
    {"username": f"test_user_{i:03d}", "email": f"test{i:03d}@example.com", "name": f"Test User {i:03d}"}
    for i in range(1, 101)
]

SAMPLE_QUERIES = [
    # Cardiovascular
    "What are the effects of aspirin on cardiovascular disease prevention?",
    "Is statin therapy effective for reducing cholesterol in elderly patients?",
    "Does blood pressure medication reduce stroke risk?",
    
    # Mental Health
    "Is cognitive behavioral therapy effective for treating depression?",
    "Does meditation reduce anxiety in adults?",
    "What is the efficacy of SSRIs for generalized anxiety disorder?",
    
    # Metabolic
    "Does intermittent fasting improve insulin sensitivity in diabetic patients?",
    "Is metformin effective for weight loss in obese individuals?",
    "What are the effects of ketogenic diet on metabolic syndrome?",
    
    # Pain Management
    "Is acupuncture effective for chronic low back pain?",
    "Does physical therapy reduce pain in arthritis patients?",
    "What is the efficacy of NSAIDs for acute musculoskeletal pain?",
    
    # Respiratory
    "Are inhaled corticosteroids effective for asthma control?",
    "Does vitamin D reduce respiratory infections in children?",
    "What is the efficacy of antibiotics for bacterial pneumonia?",
    
    # Gastrointestinal
    "Are probiotics beneficial for irritable bowel syndrome?",
    "Does gluten-free diet improve symptoms in celiac disease?",
    "What is the efficacy of proton pump inhibitors for GERD?",
    
    # Musculoskeletal
    "Does vitamin D supplementation improve bone density?",
    "Is resistance training effective for preventing osteoporosis?",
    "What are the effects of calcium on fracture risk?",
    
    # Sleep
    "Is melatonin effective for treating insomnia in adults?",
    "Does sleep hygiene education improve sleep quality?",
    "What is the efficacy of CPAP for obstructive sleep apnea?",
    
    # Nutrition
    "Does omega-3 supplementation reduce inflammation?",
    "Is the Mediterranean diet effective for cardiovascular health?",
    "What are the effects of fiber intake on colorectal cancer risk?",
    
    # Infectious Disease
    "What is the efficacy of influenza vaccine in elderly populations?",
    "Does hand washing reduce respiratory infection transmission?",
    "Are antibiotics effective for urinary tract infections?",
]


# ============================================================================
# Database Operations
# ============================================================================

def create_test_user(
    session, username: str, email: str, name: str
) -> User:
    """Create a test user in the database."""
    # Check if user already exists
    result = session.execute(
        select(User).where(User.username == username)
    )
    existing_user = result.scalar_one_or_none()
    
    if existing_user:
        logger.info(f"User already exists: {username}")
        return existing_user
    
    # Create new user with hashed password
    user = User(
        username=username,
        email=email,
        name=name,
        password_hash=pwd_context.hash(TEST_PASSWORD),
        created_at=datetime.now(timezone.utc),
    )
    session.add(user)
    session.flush()
    
    logger.info(f"Created user: {username}")
    return user


def clean_test_data(session):
    """Remove all test data from the database."""
    # Delete test users and cascading data
    result = session.execute(
        select(User).where(User.username.like("test_user_%"))
    )
    test_users = result.scalars().all()
    
    for user in test_users:
        session.delete(user)
    
    session.commit()
    logger.info(f"Deleted {len(test_users)} test users and associated data")


# ============================================================================
# Data Generation Functions
# ============================================================================

def generate_test_data(
    num_users: int = 20,
    clean_first: bool = False,
) -> Dict[str, List]:
    """
    Generate test data for load testing.
    
    Args:
        num_users: Number of test users to create
        clean_first: Whether to clean existing test data first
        
    Returns:
        Dictionary with created users and sample queries
    """
    logger.info("=" * 80)
    logger.info("🔧 GENERATING TEST DATA")
    logger.info("=" * 80)
    logger.info(f"Users to create: {num_users}")
    logger.info(f"Password for all test users: {TEST_PASSWORD}")
    logger.info("=" * 80)
    
    results = {
        "users": [],
        "password": TEST_PASSWORD,
        "sample_queries": SAMPLE_QUERIES,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    session = SessionLocal()
    try:
        # Clean existing test data if requested
        if clean_first:
            logger.info("Cleaning existing test data...")
            clean_test_data(session)
        
        # Create users
        logger.info(f"Creating {num_users} test users...")
        for i in range(num_users):
            user_data = SAMPLE_USERS[i % len(SAMPLE_USERS)]
            
            try:
                user = create_test_user(
                    session,
                    username=user_data["username"],
                    email=user_data["email"],
                    name=user_data["name"],
                )
                
                results["users"].append({
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "name": user.name,
                })
                
                session.commit()
                
            except Exception as e:
                logger.error(f"Error creating user {user_data['username']}: {e}")
                session.rollback()
                continue
    finally:
        session.close()
    
    logger.info("=" * 80)
    logger.info("✅ TEST DATA GENERATION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Created {len(results['users'])} users")
    logger.info(f"Password: {TEST_PASSWORD}")
    logger.info(f"Available {len(results['sample_queries'])} sample queries")
    logger.info("=" * 80)
    
    return results


def export_test_data(data: Dict, output_file: str):
    """Export test data to JSON file."""
    output_path = Path(output_file)
    
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    
    logger.info(f"Exported test data to: {output_path}")


def print_summary(data: Dict):
    """Print summary of generated test data."""
    print("\n" + "=" * 80)
    print("📊 TEST DATA SUMMARY")
    print("=" * 80)
    
    print(f"\n👥 USERS ({len(data['users'])}):")
    for i, user in enumerate(data["users"][:5], 1):
        print(f"  {i}. {user['username']} ({user['email']})")
    if len(data["users"]) > 5:
        print(f"  ... and {len(data['users']) - 5} more")
    
    print(f"\n🔑 PASSWORD: {data['password']}")
    
    print(f"\n📝 SAMPLE QUERIES ({len(data['sample_queries'])}):")
    for i, query in enumerate(data["sample_queries"][:5], 1):
        print(f"  {i}. {query[:70]}...")
    if len(data["sample_queries"]) > 5:
        print(f"  ... and {len(data['sample_queries']) - 5} more")
    
    print("\n" + "=" * 80)
    print("🚀 READY FOR LOAD TESTING")
    print("=" * 80)
    print("\nQuick Start:")
    print(f"  1. Use any username (test_user_XXX) with password: {data['password']}")
    print("  2. Start API: poetry run uvicorn query_refinement_module.api.main:app")
    print("  3. Run: poetry run locust -f tests/load/locustfile.py")
    print("  4. Open: http://localhost:8089")
    print("=" * 80)


# ============================================================================
# CLI
# ============================================================================

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate test data for load testing"
    )
    parser.add_argument(
        "--users",
        type=int,
        default=20,
        help="Number of test users to create (default: 20)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean existing test data before generating",
    )
    parser.add_argument(
        "--export",
        type=str,
        help="Export test data to JSON file",
    )
    
    args = parser.parse_args()
    
    try:
        # Generate test data
        data = generate_test_data(
            num_users=args.users,
            clean_first=args.clean,
        )
        
        # Export if requested
        if args.export:
            export_test_data(data, args.export)
        
        # Print summary
        print_summary(data)
        
    except Exception as e:
        logger.error(f"Error generating test data: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
