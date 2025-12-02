"""
Pydantic schemas for request/response validation.
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


# ==========================================
# User Schemas
# ==========================================

class UserCreate(BaseModel):
    """Schema for user registration."""
    email: EmailStr
    name: str
    password: str = Field(..., min_length=8)


class UserResponse(BaseModel):
    """Schema for user data in responses."""
    id: int
    email: str
    name: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class Token(BaseModel):
    """Schema for JWT token response."""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Schema for decoded token data."""
    email: Optional[str] = None


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
    original_query: str = Field(..., min_length=1)
    session_id: int


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
    query_id: Optional[int] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    comments: Optional[str] = None


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
