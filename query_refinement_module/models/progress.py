"""
Progress tracking models for real-time refinement status updates.

Provides polling-based progress tracking for long-running operations.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class ProgressStage(str, Enum):
    """Refinement workflow stages for progress tracking."""
    
    # Initial stages
    CREATED = "created"
    QUEUED = "queued"
    
    # Analysis stages
    EXTRACTING_ASPECTS = "extracting_aspects"
    ASPECTS_EXTRACTED = "aspects_extracted"
    
    # Suggestion generation
    GENERATING_SUGGESTIONS = "generating_suggestions"
    SUGGESTIONS_READY = "suggestions_ready"
    
    # User interaction
    WAITING_FOR_USER = "waiting_for_user"
    USER_REFINING = "user_refining"
    
    # Synthesis stages
    SYNTHESIZING = "synthesizing"
    SYNTHESIS_COMPLETE = "synthesis_complete"
    
    # Terminal states
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProgressStatus(BaseModel):
    """Real-time progress status for a refinement query."""
    
    query_id: str = Field(..., description="Unique query identifier")
    stage: ProgressStage = Field(..., description="Current processing stage")
    progress: float = Field(0.0, ge=0.0, le=1.0, description="Progress percentage (0.0 to 1.0)")
    
    message: str = Field(..., description="Human-readable status message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional stage-specific details")
    
    started_at: datetime = Field(..., description="Query creation timestamp")
    updated_at: datetime = Field(..., description="Last progress update timestamp")
    elapsed_seconds: float = Field(..., description="Total elapsed time in seconds")
    
    # Operation-specific metadata
    turn_number: Optional[int] = Field(None, description="Current turn number in multi-turn refinement")
    total_turns: Optional[int] = Field(None, description="Expected total turns (if known)")
    aspects_count: Optional[int] = Field(None, description="Number of aspects extracted")
    suggestions_count: Optional[int] = Field(None, description="Number of suggestions generated")
    
    # Performance tracking
    llm_calls_made: int = Field(0, description="Number of LLM API calls made so far")
    estimated_completion_seconds: Optional[float] = Field(None, description="Estimated seconds until completion")
    
    # Error information (for failed state)
    error: Optional[str] = Field(None, description="Error message if failed")
    
    class Config:
        json_schema_extra = {
            "example": {
                "query_id": "query_abc123",
                "stage": "generating_suggestions",
                "progress": 0.4,
                "message": "Generating refinement suggestions (turn 2 of 3)...",
                "details": {
                    "framework": "pico_advanced",
                    "current_aspect": "Intervention"
                },
                "started_at": "2026-02-11T10:30:00Z",
                "updated_at": "2026-02-11T10:30:08Z",
                "elapsed_seconds": 8.2,
                "turn_number": 2,
                "total_turns": 3,
                "aspects_count": 5,
                "suggestions_count": 12,
                "llm_calls_made": 2,
                "estimated_completion_seconds": 12.0,
                "error": None
            }
        }


class ProgressUpdate(BaseModel):
    """Internal model for updating progress (not exposed via API)."""
    
    stage: ProgressStage
    progress: float
    message: str
    details: Optional[Dict[str, Any]] = None
    
    turn_number: Optional[int] = None
    total_turns: Optional[int] = None
    aspects_count: Optional[int] = None
    suggestions_count: Optional[int] = None
    llm_calls_made: Optional[int] = None
    estimated_completion_seconds: Optional[float] = None
    error: Optional[str] = None


# Progress stage mappings for easy calculation
STAGE_PROGRESS_MAP: Dict[ProgressStage, float] = {
    ProgressStage.CREATED: 0.0,
    ProgressStage.QUEUED: 0.05,
    ProgressStage.EXTRACTING_ASPECTS: 0.10,
    ProgressStage.ASPECTS_EXTRACTED: 0.20,
    ProgressStage.GENERATING_SUGGESTIONS: 0.30,
    ProgressStage.SUGGESTIONS_READY: 0.50,
    ProgressStage.WAITING_FOR_USER: 0.50,
    ProgressStage.USER_REFINING: 0.60,
    ProgressStage.SYNTHESIZING: 0.80,
    ProgressStage.SYNTHESIS_COMPLETE: 0.95,
    ProgressStage.COMPLETED: 1.0,
    ProgressStage.FAILED: 1.0,
    ProgressStage.CANCELLED: 1.0,
}


# User-friendly messages for each stage
STAGE_MESSAGES: Dict[ProgressStage, str] = {
    ProgressStage.CREATED: "Query received",
    ProgressStage.QUEUED: "Queued for processing",
    ProgressStage.EXTRACTING_ASPECTS: "Analyzing query structure...",
    ProgressStage.ASPECTS_EXTRACTED: "Query structure analyzed",
    ProgressStage.GENERATING_SUGGESTIONS: "Generating refinement suggestions...",
    ProgressStage.SUGGESTIONS_READY: "Refinement suggestions ready for review",
    ProgressStage.WAITING_FOR_USER: "Waiting for your refinement decisions",
    ProgressStage.USER_REFINING: "Processing your refinements...",
    ProgressStage.SYNTHESIZING: "Synthesizing final refined query...",
    ProgressStage.SYNTHESIS_COMPLETE: "Refined query complete",
    ProgressStage.COMPLETED: "Refinement completed successfully",
    ProgressStage.FAILED: "Refinement failed",
    ProgressStage.CANCELLED: "Refinement cancelled",
}
