"""
API Examples for Query Refinement Module

This file demonstrates how to build a stateless REST API using the query refinement module.
Shows session persistence, error handling, and complete request/response flows.
"""

# ============================================================================
# Example 1: FastAPI Implementation with Redis Session Storage
# ============================================================================

"""
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import redis
import pickle
import uuid

from query_refinement_module import QueryRefinementManager, QueryRefinementSession
from query_refinement_module.interfaces import SessionStorageInterface
from query_refinement_module.schema import RefinementAspect, load_refinement_framework


# ===== Session Storage Implementation =====

class RedisSessionStorage(SessionStorageInterface):
    '''Redis-based session persistence.'''
    
    def __init__(self, redis_client: redis.Redis, ttl_seconds: int = 3600):
        self.redis = redis_client
        self.ttl = ttl_seconds
    
    def save_session(self, session_id: str, session: QueryRefinementSession) -> None:
        '''Serialize and save session to Redis with TTL.'''
        key = f"refinement_session:{session_id}"
        serialized = pickle.dumps(session)
        self.redis.setex(key, self.ttl, serialized)
    
    def load_session(self, session_id: str) -> QueryRefinementSession:
        '''Deserialize and load session from Redis.'''
        key = f"refinement_session:{session_id}"
        serialized = self.redis.get(key)
        if not serialized:
            raise KeyError(f"Session {session_id} not found or expired")
        return pickle.loads(serialized)
    
    def delete_session(self, session_id: str) -> None:
        '''Remove session from Redis.'''
        key = f"refinement_session:{session_id}"
        self.redis.delete(key)
    
    def session_exists(self, session_id: str) -> bool:
        '''Check if session exists in Redis.'''
        key = f"refinement_session:{session_id}"
        return self.redis.exists(key) > 0


# ===== Request/Response Models =====

class InitializeRequest(BaseModel):
    query: str
    framework_id: str  # e.g., "pico", "solace_ai", "custom"


class InitializeResponse(BaseModel):
    session_id: str
    summary: Dict[str, Any]
    # Example summary structure:
    # {
    #   "is_complete": false,
    #   "total_aspects": 4,
    #   "aspects_needing_refinement": 2,
    #   "aspects_clear": 2,
    #   "aspects": [
    #     {
    #       "id": "outcome",
    #       "name": "Outcome",
    #       "description": "What outcome is being measured",
    #       "status": "needs_refinement",
    #       "reason": "Stroke is mentioned but not specific...",
    #       "suggested_question": "What specific stroke outcomes are you interested in?"
    #     },
    #     ...
    #   ]
    # }


class ProcessStepRequest(BaseModel):
    session_id: str
    user_response: Optional[str] = None  # User's answer to previous question


class ProcessStepResponse(BaseModel):
    done: bool
    aspect: Optional[Dict[str, Any]] = None
    # When done=False, aspect contains:
    # {
    #   "aspect_id": "outcome",
    #   "aspect_name": "Outcome",
    #   "question": "What specific stroke outcomes...",
    #   "response": "...",  # LLM's generated question
    #   "error": false
    # }
    summary: Optional[Dict[str, Any]] = None  # When done=True


# ===== FastAPI Application =====

app = FastAPI(title="Query Refinement API")

# Initialize dependencies
redis_client = redis.Redis(host='localhost', port=6379, db=0)
session_storage = RedisSessionStorage(redis_client)

# These would be injected via dependency injection in production
llm_provider = ...  # Your LLM provider implementation
query_analyzer = ...  # Your query analyzer implementation
tracing_provider = ...  # Your tracing provider implementation

manager = QueryRefinementManager(
    llm_provider=llm_provider,
    query_analyzer=query_analyzer,
    tracing_provider=tracing_provider
)


@app.post("/api/v1/refine/initialize", response_model=InitializeResponse)
async def initialize_refinement(request: InitializeRequest):
    '''
    Initialize a new refinement session.
    
    Performs dependency-aware analysis of all aspects and returns
    a summary of what needs refinement and why.
    
    Example request:
    POST /api/v1/refine/initialize
    {
      "query": "effects of aspirin on stroke",
      "framework_id": "pico"
    }
    
    Example response:
    {
      "session_id": "550e8400-e29b-41d4-a716-446655440000",
      "summary": {
        "is_complete": false,
        "total_aspects": 4,
        "aspects_needing_refinement": 1,
        "aspects_clear": 3,
        "aspects": [...]
      }
    }
    '''
    try:
        # Load refinement framework
        framework = load_refinement_framework(request.framework_id)
        
        # Initialize session (analyzes all aspects)
        session = manager.initialize(
            original_query=request.query,
            refinement_framework=framework
        )
        
        # Generate session ID
        session_id = str(uuid.uuid4())
        
        # Save session to Redis
        session_storage.save_session(session_id, session)
        
        # Get user-friendly summary
        summary = manager.get_initialization_summary(session)
        
        return InitializeResponse(
            session_id=session_id,
            summary=summary
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/refine/step", response_model=ProcessStepResponse)
async def process_refinement_step(request: ProcessStepRequest):
    '''
    Process one refinement step (one aspect interaction).
    
    If user_response is provided, it's stored for the current active aspect.
    Then the next aspect needing refinement is processed with an LLM call.
    
    Example request (first call - no user response yet):
    POST /api/v1/refine/step
    {
      "session_id": "550e8400-e29b-41d4-a716-446655440000"
    }
    
    Example response:
    {
      "done": false,
      "aspect": {
        "aspect_id": "outcome",
        "aspect_name": "Outcome",
        "question": "Outcome",
        "response": "What specific stroke outcomes are you interested in?",
        "error": false
      }
    }
    
    Example request (with user answer):
    POST /api/v1/refine/step
    {
      "session_id": "550e8400-e29b-41d4-a716-446655440000",
      "user_response": "stroke recurrence within 1 year"
    }
    '''
    try:
        # Load session from Redis
        if not session_storage.session_exists(request.session_id):
            raise HTTPException(status_code=404, detail="Session not found or expired")
        
        session = session_storage.load_session(request.session_id)
        
        # If user provided a response, store it for the current active aspect
        if request.user_response:
            step = session.get_active_step()
            if step:
                step.add_follow_up(
                    question=step.analysis_suggested_question or step.refinement_aspect.name,
                    response=request.user_response
                )
                step.is_complete = True
        
        # Process next step (calls LLM for next aspect needing refinement)
        result = manager.process_next_step(session)
        
        # Save updated session
        session_storage.save_session(request.session_id, session)
        
        if result is None:
            # No more steps - refinement complete
            summary = session.get_step_summary()
            return ProcessStepResponse(done=True, summary=summary)
        
        return ProcessStepResponse(done=False, aspect=result)
    
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/refine/session/{session_id}/summary")
async def get_session_summary(session_id: str):
    '''
    Get current status of a refinement session.
    
    Example response:
    {
      "is_complete": false,
      "total_steps": 4,
      "completed": 2,
      "needs_review": 0,
      "in_progress": 2,
      "total_follow_ups": 2,
      "steps": [...]
    }
    '''
    try:
        if not session_storage.session_exists(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_storage.load_session(session_id)
        return session.get_step_summary()
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/v1/refine/session/{session_id}")
async def delete_session(session_id: str):
    '''Delete a refinement session (cleanup).'''
    try:
        session_storage.delete_session(session_id)
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
"""


# ============================================================================
# Example 2: Complete Client-Side Flow
# ============================================================================

"""
import requests

# API base URL
API_BASE = "http://localhost:8000/api/v1/refine"

# Step 1: Initialize refinement session
def initialize_session(query: str, framework_id: str = "pico"):
    response = requests.post(
        f"{API_BASE}/initialize",
        json={"query": query, "framework_id": framework_id}
    )
    response.raise_for_status()
    return response.json()

# Step 2: Process refinement interactively
def refine_query_interactive(session_id: str):
    while True:
        # Get next step
        response = requests.post(
            f"{API_BASE}/step",
            json={"session_id": session_id}
        )
        response.raise_for_status()
        data = response.json()
        
        if data["done"]:
            print("\\n✅ Refinement complete!")
            print(f"Summary: {data['summary']}")
            break
        
        aspect = data["aspect"]
        if aspect.get("error"):
            print(f"\\n❌ Error processing {aspect['aspect_name']}")
            break
        
        # Show question to user
        print(f"\\n[{aspect['aspect_name']}]")
        print(f"Q: {aspect['response']}")
        
        # Get user's answer
        user_answer = input("A: ").strip()
        
        if not user_answer:
            break
        
        # Submit answer
        response = requests.post(
            f"{API_BASE}/step",
            json={
                "session_id": session_id,
                "user_response": user_answer
            }
        )
        response.raise_for_status()

# Usage:
result = initialize_session("effects of aspirin on stroke")
print(f"Session ID: {result['session_id']}")
print(f"Summary: {result['summary']}")

if not result['summary']['is_complete']:
    print(f"\\n{result['summary']['aspects_needing_refinement']} aspects need refinement")
    for aspect in result['summary']['aspects']:
        if aspect['status'] == 'needs_refinement':
            print(f"  - {aspect['name']}: {aspect.get('reason', 'N/A')}")
    
    proceed = input("\\nStart refinement? (y/n): ")
    if proceed.lower() == 'y':
        refine_query_interactive(result['session_id'])
"""


# ============================================================================
# Example 3: Batch Processing (Non-Interactive)
# ============================================================================

"""
def refine_query_batch(query: str, framework_id: str, max_iterations: int = 10):
    '''
    Refine a query automatically without user interaction.
    Useful for testing or automated workflows.
    '''
    # Initialize
    result = initialize_session(query, framework_id)
    session_id = result['session_id']
    
    if result['summary']['is_complete']:
        return {"status": "already_complete", "session_id": session_id}
    
    # Auto-refine with default/generated responses
    iterations = 0
    while iterations < max_iterations:
        response = requests.post(
            f"{API_BASE}/step",
            json={
                "session_id": session_id,
                "user_response": "[AUTO] Default response"  # Could use LLM to generate
            }
        )
        response.raise_for_status()
        data = response.json()
        
        if data["done"]:
            return {"status": "complete", "summary": data["summary"]}
        
        iterations += 1
    
    return {"status": "max_iterations_reached", "iterations": iterations}
"""


# ============================================================================
# Example 4: Alternative Storage - PostgreSQL
# ============================================================================

"""
from sqlalchemy import create_engine, Column, String, LargeBinary, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
import pickle

Base = declarative_base()

class RefinementSessionModel(Base):
    __tablename__ = 'refinement_sessions'
    
    session_id = Column(String, primary_key=True)
    session_data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


class PostgreSQLSessionStorage(SessionStorageInterface):
    '''PostgreSQL-based session persistence.'''
    
    def __init__(self, db_url: str, ttl_seconds: int = 3600):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session_factory = Session
        self.ttl = ttl_seconds
    
    def save_session(self, session_id: str, session: QueryRefinementSession) -> None:
        db_session = self.session_factory()
        try:
            serialized = pickle.dumps(session)
            expires_at = datetime.utcnow() + timedelta(seconds=self.ttl)
            
            existing = db_session.query(RefinementSessionModel).filter_by(
                session_id=session_id
            ).first()
            
            if existing:
                existing.session_data = serialized
                existing.expires_at = expires_at
            else:
                model = RefinementSessionModel(
                    session_id=session_id,
                    session_data=serialized,
                    expires_at=expires_at
                )
                db_session.add(model)
            
            db_session.commit()
        finally:
            db_session.close()
    
    def load_session(self, session_id: str) -> QueryRefinementSession:
        db_session = self.session_factory()
        try:
            model = db_session.query(RefinementSessionModel).filter_by(
                session_id=session_id
            ).first()
            
            if not model:
                raise KeyError(f"Session {session_id} not found")
            
            if datetime.utcnow() > model.expires_at:
                db_session.delete(model)
                db_session.commit()
                raise KeyError(f"Session {session_id} has expired")
            
            return pickle.loads(model.session_data)
        finally:
            db_session.close()
    
    def delete_session(self, session_id: str) -> None:
        db_session = self.session_factory()
        try:
            db_session.query(RefinementSessionModel).filter_by(
                session_id=session_id
            ).delete()
            db_session.commit()
        finally:
            db_session.close()
    
    def session_exists(self, session_id: str) -> bool:
        db_session = self.session_factory()
        try:
            count = db_session.query(RefinementSessionModel).filter_by(
                session_id=session_id
            ).count()
            return count > 0
        finally:
            db_session.close()
"""

print(__doc__)
