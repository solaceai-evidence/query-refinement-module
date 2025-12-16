"""
Pydantic schemas for request/response validation.
"""
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List
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
    id: int
    username: str
    email: Optional[str] = None
    name: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class Token(BaseModel):
    """Schema for JWT token response."""
    access_token: str
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
    id: int
    user_id: int
    started_at: datetime
    ended_at: Optional[datetime] = None
    status: str
    
    class Config:
        from_attributes = True


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
    """Schema for query in responses."""
    id: int
    session_id: int
    original_query: str
    refined_query: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ==========================================
# Refinement Step Schemas
# ==========================================

class RefinementStepCreate(BaseModel):
    """Schema for creating a refinement step."""
    query_id: int
    aspect_name: str


class RefinementStepResponse(BaseModel):
    """Schema for refinement step in responses."""
    id: int
    query_id: int
    aspect_name: str
    created_at: datetime
    
    class Config:
        from_attributes = True


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
    id: int
    refinement_step_id: int
    question: str
    answer: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


# ==========================================
# Feedback Schemas
# ==========================================

class FeedbackCreate(BaseModel):
    """Schema for creating feedback."""
    query_id: Optional[int] = Field(None, gt=0, description="Optional query ID this feedback is about")
    rating: Optional[int] = Field(None, ge=1, le=5, description="Rating from 1 (poor) to 5 (excellent)")
    comments: Optional[str] = Field(None, max_length=2000, description="Optional feedback comments")
    
    @field_validator('comments')
    @classmethod
    def comments_not_just_whitespace(cls, v: Optional[str]) -> Optional[str]:
        """Validate that comments are not just whitespace if provided."""
        if v is not None and v.strip() == "":
            raise ValueError("Comments cannot be just whitespace")
        return v.strip() if v else None
    
    @field_validator('rating')
    @classmethod
    def validate_rating_or_comments(cls, v: Optional[int], info) -> Optional[int]:
        """Ensure at least rating or comments is provided."""
        # Note: This validator runs after comments, so we can't access it here
        # We'll check this in the endpoint instead
        return v


class FeedbackResponse(BaseModel):
    """Schema for feedback in responses."""
    id: int
    user_id: int
    query_id: Optional[int] = None
    rating: Optional[int] = None
    comments: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True
