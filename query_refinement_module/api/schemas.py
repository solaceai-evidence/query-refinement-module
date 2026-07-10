"""
Pydantic schemas for request/response validation.
"""
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from typing import Any, Dict, Optional, List
from datetime import datetime
import re


# ==========================================
# User Schemas
# ==========================================

class UserCreate(BaseModel):
    """Schema for user registration."""
    username: str = Field(
        ..., 
        min_length=3, 
        max_length=50, 
        pattern=r'^[a-zA-Z0-9_-]+$',
        description="Username (3-50 chars, alphanumeric, underscore, hyphen only)"
    )
    email: Optional[EmailStr] = Field(None, description="Optional email address")
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="User's display name")
    password: str = Field(
        ..., 
        min_length=8,
        max_length=128,
        description="Password must be at least 8 characters with uppercase, lowercase, digit, and special character"
    )
    
    @field_validator('username')
    @classmethod
    def username_valid(cls, v: str) -> str:
        """Validate username format."""
        if not v or not v.strip():
            raise ValueError("Username cannot be empty or just whitespace")
        v = v.strip()
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("Username can only contain letters, numbers, underscores, and hyphens")
        return v
    
    @field_validator('name')
    @classmethod
    def name_not_empty(cls, v: Optional[str]) -> Optional[str]:
        """Validate that name is not just whitespace if provided."""
        if v is not None:
            if not v.strip():
                raise ValueError("Name cannot be empty or just whitespace")
            return v.strip()
        return v
    
    @field_validator('password')
    @classmethod
    def password_strength(cls, v: str) -> str:
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r'[A-Z]', v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r'[a-z]', v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r'[0-9]', v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            raise ValueError("Password must contain at least one special character")
        return v


class UserResponse(BaseModel):
    """Schema for user data in responses."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    username: str
    email: Optional[str] = None
    name: Optional[str] = None
    created_at: datetime


class Token(BaseModel):
    """Schema for JWT token response (legacy / integration-service use)."""
    access_token: str
    token_type: str = "bearer"


class LoginResponse(BaseModel):
    """Schema for the browser login response.

    The JWT is delivered as an httpOnly cookie; this body only carries
    non-sensitive confirmation data needed by the browser client.
    """
    status: str = "ok"
    username: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Schema for decoded token data."""
    username: Optional[str] = None


# ==========================================
# Query Session Schemas
# ==========================================

class QuerySessionCreate(BaseModel):
    """Schema for creating a new query session."""
    pass  # No additional fields needed; user_id comes from auth


class QuerySessionResponse(BaseModel):
    """Schema for query session in responses."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: int
    started_at: datetime
    ended_at: Optional[datetime] = None
    status: str


# ==========================================
# Query Schemas
# ==========================================

class QueryCreate(BaseModel):
    """Schema for creating a new query."""
    original_query: str = Field(
        ..., 
        min_length=1,
        max_length=5000,
        description="The original query to refine"
    )
    session_id: int = Field(..., gt=0, description="Valid session ID")
    
    @field_validator('original_query')
    @classmethod
    def query_not_empty(cls, v: str) -> str:
        """Validate that query is not just whitespace."""
        if not v or not v.strip():
            raise ValueError("Query cannot be empty or just whitespace")
        return v.strip()


class QueryUpdate(BaseModel):
    """Schema for updating a refined query."""
    refined_query: str


class QueryResponse(BaseModel):
    """Schema for query in responses - includes full QueryRefinementResponse fields."""
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    
    id: int
    session_id: int
    original_query: str
    refined_query: Optional[str] = None  # Deprecated - use integrated_statement
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    
    # QueryRefinementResponse fields exposed with canonical API names.
    integrated_statement: Optional[str] = None
    dimensions_specifications: Optional[Dict[str, Any]] = None
    search_optimized: Optional[Dict[str, Any]] = None
    search_filters: Optional[Dict[str, Any]] = None
    terminology: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    processing_log: Optional[Dict[str, Any]] = None

    @classmethod
    def from_query_record(cls, query: Any) -> "QueryResponse":
        """Build the canonical API response from a persisted query record."""
        return cls(
            id=query.id,
            session_id=query.session_id,
            original_query=query.original_query,
            refined_query=query.refined_query,
            created_at=query.created_at,
            updated_at=query.updated_at,
            completed_at=query.completed_at,
            integrated_statement=getattr(query, "integrated_statement", None),
            dimensions_specifications=getattr(query, "dimensions_specifications", None),
            search_optimized=getattr(query, "search_optimized", None),
            search_filters=getattr(query, "search_filters", None),
            terminology=getattr(query, "terminology", None),
            metadata=getattr(query, "synthesis_metadata", None),
            processing_log=getattr(query, "processing_log", None),
        )


# ==========================================
# Refinement Step Schemas
# ==========================================

class RefinementStepCreate(BaseModel):
    """Schema for creating a refinement step."""
    query_id: int
    aspect_name: str
    aspect_id: Optional[str] = None


class RefinementStepResponse(BaseModel):
    """Schema for refinement step in responses.
    
    Fields from LLM (DimensionEvaluationResponse):
    - final_value: refinement_aspect_value from LLM
    - is_complete: from LLM response
    
    Evaluation-only fields (user behavior tracking):
    - was_skipped: User used /skip command
    - user_ended_early: User used /done before LLM marked complete
    """
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    query_id: int
    aspect_id: Optional[str] = None
    aspect_name: str
    final_value: Optional[str] = None  # From LLM: current value
    is_complete: bool = False          # From LLM: complete status
    was_skipped: bool = False          # Evaluation-only: /skip command
    user_ended_early: bool = False     # Evaluation-only: /done before LLM complete
    created_at: datetime


# ==========================================
# Follow-up History Schemas
# ==========================================

class FollowUpCreate(BaseModel):
    """Schema for creating a follow-up entry."""
    refinement_step_id: int
    question: str
    answer: Optional[str] = None


class FollowUpUpdate(BaseModel):
    """Schema for updating a follow-up answer."""
    answer: str


class FollowUpResponse(BaseModel):
    """Schema for follow-up in responses."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    refinement_step_id: int
    question: str
    answer: Optional[str] = None
    created_at: datetime


# ==========================================
# Feedback Schemas
# ==========================================

class FeedbackCreate(BaseModel):
    """Schema for creating feedback - research-focused for dissertation topic refinement."""
    query_id: Optional[int] = Field(None, gt=0, description="Optional query ID this feedback is about")
    rating: Optional[int] = Field(None, ge=1, le=5, description="Optional rating (not used for research feedback)")
    comments: Optional[str] = Field(None, max_length=5000, description="Research feedback on dissertation refinement experience")
    consent_to_use_data: bool = Field(
        False,
        description=(
            "Explicit consent for the project team to retain and use this query session data "
            "and feedback for research/analysis. If false, workflow can still complete but the "
            "associated query remains unconsented and may be deleted by retention policies."
        ),
    )
    additional_metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional structured feedback payload (e.g., Likert responses, time saved, confidence before/after)."
    )
    
    @field_validator('comments')
    @classmethod
    def normalize_comments(cls, v: Optional[str]) -> Optional[str]:
        """Treat comments as optional; trim non-empty values and normalize blank to None."""
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned or None


class FeedbackResponse(BaseModel):
    """Schema for feedback in responses."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: int
    query_id: Optional[int] = None
    rating: Optional[int] = None
    comments: Optional[str] = None
    additional_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
