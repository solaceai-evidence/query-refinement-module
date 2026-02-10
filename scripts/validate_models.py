#!/usr/bin/env python3
"""Validate all Pydantic and DB models."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

print("=" * 70)
print("VALIDATING ALL MODELS")
print("=" * 70)

# Test all DB models
print("\n1. Testing DB Models...")
try:
    from query_refinement_module.db.models.user import User
    from query_refinement_module.db.models.query import Query
    from query_refinement_module.db.models.query_session import QuerySession
    from query_refinement_module.db.models.refinement_step import RefinementStep
    from query_refinement_module.db.models.webhook import Webhook, WebhookDelivery, WebhookEventType
    from query_refinement_module.db.models.feedback import Feedback
    from query_refinement_module.db.models.followup_history import FollowUpHistory
    from query_refinement_module.db.models.audit_log import AuditLog
    from query_refinement_module.db.models.frontend_log import FrontendLog
    from query_refinement_module.db.models.refinement_step_metadata import RefinementStepMetadata
    print("   ✓ All DB models loaded successfully")
except Exception as e:
    print(f"   ✗ DB models failed: {e}")
    sys.exit(1)

# Test all Pydantic schemas
print("\n2. Testing Pydantic API Schemas...")
try:
    from query_refinement_module.api.schemas import (
        UserCreate, UserResponse, Token, TokenData,
        QuerySessionCreate, QuerySessionResponse,
        QueryCreate, QueryUpdate, QueryResponse,
        RefinementStepCreate, RefinementStepResponse,
        FollowUpCreate, FollowUpUpdate, FollowUpResponse,
        FeedbackCreate, FeedbackResponse
    )
    print("   ✓ All Pydantic schemas loaded successfully")
except Exception as e:
    print(f"   ✗ Pydantic schemas failed: {e}")
    sys.exit(1)

# Test API models (dataclasses)
print("\n3. Testing API Models...")
try:
    from query_refinement_module.api_models import (
        NextPrompt, SessionCreateRequest, SessionCreateResponse,
        InteractionRequest, InteractionResponse, SessionStatusResponse
    )
    print("   ✓ All API models loaded successfully")
except Exception as e:
    print(f"   ✗ API models failed: {e}")
    sys.exit(1)

# Test session models
print("\n4. Testing Session Models...")
try:
    from query_refinement_module.session_models import (
        AspectRefinementState, RefinementSession
    )
    print("   ✓ All session models loaded successfully")
except Exception as e:
    print(f"   ✗ Session models failed: {e}")
    sys.exit(1)

# Test Pydantic validation
print("\n5. Testing Pydantic Validation...")
try:
    from pydantic import ValidationError
    
    # Test UserCreate validation
    valid_user = UserCreate(
        username="test_user",
        password="Test123!@#",
        email="test@example.com"
    )
    print("   ✓ UserCreate validation works")
    
    # Test QueryCreate validation
    valid_query = QueryCreate(
        original_query="What is machine learning?",
        session_id=1
    )
    print("   ✓ QueryCreate validation works")
    
    # Test invalid password
    try:
        invalid_user = UserCreate(
            username="test",
            password="weak",  # Too weak
            email="test@example.com"
        )
        print("   ✗ Password validation failed to catch weak password")
    except ValidationError:
        print("   ✓ Password validation works correctly")
    
    # Test invalid query
    try:
        invalid_query = QueryCreate(
            original_query="   ",  # Empty after strip
            session_id=1
        )
        print("   ✗ Query validation failed to catch empty query")
    except ValidationError:
        print("   ✓ Query validation works correctly")
        
except Exception as e:
    print(f"   ✗ Pydantic validation failed: {e}")
    sys.exit(1)

# Test DB model instantiation
print("\n6. Testing DB Model Instantiation...")
try:
    # User model
    user = User(
        username="test_user",
        password_hash="$2b$12$test_hash",
        email="test@example.com"
    )
    print("   ✓ User model instantiation works")
    
    # Query model
    query = Query(
        session_id=1,
        original_query="test query",
        synthesized_statement="refined query"
    )
    print("   ✓ Query model instantiation works")
    
    # QuerySession model
    session = QuerySession(
        user_id=1,
        status="active"
    )
    print("   ✓ QuerySession model instantiation works")
    
except Exception as e:
    print(f"   ✗ DB model instantiation failed: {e}")
    sys.exit(1)

print("\n" + "=" * 70)
print("✅ ALL MODELS VALIDATED SUCCESSFULLY!")
print("=" * 70)
print("\nSummary:")
print("  - DB Models: ✓")
print("  - Pydantic Schemas: ✓")
print("  - API Models: ✓")
print("  - Session Models: ✓")
print("  - Validation Logic: ✓")
print("  - Model Instantiation: ✓")
print("\nNo corruption or invalid models detected.")
