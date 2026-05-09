"""
Tests for real-time progress tracking.
"""
import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, Mock, patch

from query_refinement_module.api.main import app
from query_refinement_module.api.routes import refinement as refinement_routes
from query_refinement_module.models.progress import (
    ProgressStage,
    ProgressStatus,
    ProgressUpdate,
    STAGE_PROGRESS_MAP,
)
from query_refinement_module.services.progress_tracker import (
    ProgressTracker,
    get_progress_tracker,
)


client = TestClient(app)


class TestProgressTracker:
    """Test progress tracker service."""
    
    @pytest.mark.asyncio
    async def test_create_progress(self):
        """Test creating initial progress entry."""
        tracker = ProgressTracker(ttl_seconds=3600)
        
        progress = await tracker.create(
            query_id="test_query_1",
            initial_stage=ProgressStage.CREATED
        )
        
        assert progress.query_id == "test_query_1"
        assert progress.stage == ProgressStage.CREATED
        assert progress.progress == 0.0
        assert "Query received" in progress.message
        assert progress.llm_calls_made == 0
    
    @pytest.mark.asyncio
    async def test_update_progress(self):
        """Test updating progress."""
        tracker = ProgressTracker()
        
        # Create initial progress
        await tracker.create("test_query_2")
        
        # Update progress
        update = ProgressUpdate(
            stage=ProgressStage.GENERATING_SUGGESTIONS,
            progress=0.4,
            message="Generating suggestions...",
            llm_calls_made=2,
            turn_number=2,
            total_turns=3
        )
        
        progress = await tracker.update("test_query_2", update)
        
        assert progress is not None
        assert progress.stage == ProgressStage.GENERATING_SUGGESTIONS
        assert progress.progress == 0.4
        assert progress.llm_calls_made == 2
        assert progress.turn_number == 2
        assert progress.total_turns == 3
    
    @pytest.mark.asyncio
    async def test_get_progress(self):
        """Test retrieving progress."""
        tracker = ProgressTracker()
        
        # Create progress
        await tracker.create("test_query_3")
        
        # Get progress
        progress = await tracker.get("test_query_3")
        
        assert progress is not None
        assert progress.query_id == "test_query_3"
        assert progress.elapsed_seconds >= 0
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_progress(self):
        """Test retrieving progress for nonexistent query."""
        tracker = ProgressTracker()
        
        progress = await tracker.get("nonexistent_query")
        
        assert progress is None
    
    @pytest.mark.asyncio
    async def test_delete_progress(self):
        """Test deleting progress."""
        tracker = ProgressTracker()
        
        # Create and delete
        await tracker.create("test_query_4")
        deleted = await tracker.delete("test_query_4")
        
        assert deleted is True
        
        # Verify deleted
        progress = await tracker.get("test_query_4")
        assert progress is None
    
    @pytest.mark.asyncio
    async def test_increment_llm_calls(self):
        """Test incrementing LLM call counter."""
        tracker = ProgressTracker()
        
        # Create progress
        await tracker.create("test_query_5")
        
        # Increment calls
        await tracker.increment_llm_calls("test_query_5")
        await tracker.increment_llm_calls("test_query_5")
        
        progress = await tracker.get("test_query_5")
        assert progress.llm_calls_made == 2
    
    @pytest.mark.asyncio
    async def test_cleanup_expired(self):
        """Test cleaning up expired progress entries."""
        tracker = ProgressTracker(ttl_seconds=0)  # Immediate expiration
        
        # Create some progress entries
        await tracker.create("query_old_1")
        await tracker.create("query_old_2")
        
        # Wait a bit
        import asyncio
        await asyncio.sleep(0.1)
        
        # Cleanup
        removed = await tracker.cleanup_expired()
        
        assert removed == 2
    
    @pytest.mark.asyncio
    async def test_progress_stages(self):
        """Test all progress stages have correct mappings."""
        for stage in ProgressStage:
            assert stage in STAGE_PROGRESS_MAP
            assert 0.0 <= STAGE_PROGRESS_MAP[stage] <= 1.0


class TestProgressAPI:
    """Test progress API endpoints."""
    
    def test_get_progress_unauthorized(self):
        """Test getting progress without authentication."""
        response = client.get("/api/v1/refinement/queries/123/progress")
        
        assert response.status_code == 401
    
    def test_get_progress_not_found(self):
        """Test getting progress for nonexistent query."""
        mock_user = Mock(id=1)
        mock_db = Mock()

        app.dependency_overrides[refinement_routes.get_current_user_or_integration] = lambda: mock_user

        def override_get_db():
            yield mock_db

        app.dependency_overrides[refinement_routes.get_db] = override_get_db

        try:
            with patch("query_refinement_module.api.routes.refinement.get_query", return_value=None):
                response = client.get("/api/v1/refinement/queries/999/progress")

                assert response.status_code == 404
        finally:
            app.dependency_overrides.pop(refinement_routes.get_current_user_or_integration, None)
            app.dependency_overrides.pop(refinement_routes.get_db, None)
    
    @pytest.mark.asyncio
    async def test_track_progress_helper(self):
        """Test track_progress convenience function."""
        from query_refinement_module.services.progress_tracker import track_progress
        
        tracker = get_progress_tracker()
        
        # Create initial progress
        await tracker.create("test_query_6")
        
        # Track progress
        await track_progress(
            query_id="test_query_6",
            stage=ProgressStage.EXTRACTING_ASPECTS,
            message="Analyzing query...",
            aspects_count=5
        )
        
        progress = await tracker.get("test_query_6")
        
        assert progress.stage == ProgressStage.EXTRACTING_ASPECTS
        assert progress.aspects_count == 5


class TestProgressIntegration:
    """Test progress tracking in refinement workflow."""
    
    @pytest.mark.asyncio
    async def test_progress_lifecycle(self):
        """Test full progress lifecycle from start to completion."""
        tracker = ProgressTracker()
        query_id = "lifecycle_test"
        
        # Start refinement
        await tracker.create(query_id, ProgressStage.CREATED)
        progress = await tracker.get(query_id)
        assert progress.stage == ProgressStage.CREATED
        
        # Extract aspects
        await tracker.update(query_id, ProgressUpdate(
            stage=ProgressStage.EXTRACTING_ASPECTS,
            progress=0.1,
            message="Analyzing query structure..."
        ))
        progress = await tracker.get(query_id)
        assert progress.stage == ProgressStage.EXTRACTING_ASPECTS
        
        # Aspects extracted
        await tracker.update(query_id, ProgressUpdate(
            stage=ProgressStage.ASPECTS_EXTRACTED,
            progress=0.2,
            message="Identified 5 aspects",
            aspects_count=5
        ))
        progress = await tracker.get(query_id)
        assert progress.aspects_count == 5
        
        # Generate suggestions
        await tracker.update(query_id, ProgressUpdate(
            stage=ProgressStage.GENERATING_SUGGESTIONS,
            progress=0.4,
            message="Generating refinement suggestions (turn 1 of 3)...",
            turn_number=1,
            total_turns=3,
            llm_calls_made=1
        ))
        progress = await tracker.get(query_id)
        assert progress.turn_number == 1
        
        # Suggestions ready
        await tracker.update(query_id, ProgressUpdate(
            stage=ProgressStage.SUGGESTIONS_READY,
            progress=0.5,
            message="Refinement suggestions ready",
            suggestions_count=12
        ))
        progress = await tracker.get(query_id)
        assert progress.suggestions_count == 12
        
        # Waiting for user
        await tracker.update(query_id, ProgressUpdate(
            stage=ProgressStage.WAITING_FOR_USER,
            progress=0.5,
            message="Waiting for your refinement decisions"
        ))
        progress = await tracker.get(query_id)
        assert progress.stage == ProgressStage.WAITING_FOR_USER
        
        # User refining
        await tracker.update(query_id, ProgressUpdate(
            stage=ProgressStage.USER_REFINING,
            progress=0.6,
            message="Processing your refinements..."
        ))
        
        # Synthesizing
        await tracker.update(query_id, ProgressUpdate(
            stage=ProgressStage.SYNTHESIZING,
            progress=0.8,
            message="Synthesizing final refined query...",
            llm_calls_made=3
        ))
        progress = await tracker.get(query_id)
        assert progress.stage == ProgressStage.SYNTHESIZING
        
        # Complete
        await tracker.update(query_id, ProgressUpdate(
            stage=ProgressStage.COMPLETED,
            progress=1.0,
            message="Refinement completed successfully"
        ))
        progress = await tracker.get(query_id)
        assert progress.stage == ProgressStage.COMPLETED
        assert progress.progress == 1.0
    
    @pytest.mark.asyncio
    async def test_progress_with_errors(self):
        """Test progress tracking when refinement fails."""
        tracker = ProgressTracker()
        query_id = "error_test"
        
        await tracker.create(query_id)
        
        # Simulate failure
        await tracker.update(query_id, ProgressUpdate(
            stage=ProgressStage.FAILED,
            progress=1.0,
            message="Refinement failed",
            error="LLM service unavailable"
        ))
        
        progress = await tracker.get(query_id)
        assert progress.stage == ProgressStage.FAILED
        assert progress.error is not None
        assert "unavailable" in progress.error


class TestProgressPolling:
    """Test polling-based progress retrieval."""
    
    @pytest.mark.asyncio
    async def test_polling_interval(self):
        """Test that progress updates are visible within polling interval."""
        tracker = ProgressTracker()
        query_id = "polling_test"
        
        # Create initial progress
        await tracker.create(query_id)
        
        # Simulate updates at different times
        import asyncio
        
        await tracker.update(query_id, ProgressUpdate(
            stage=ProgressStage.EXTRACTING_ASPECTS,
            progress=0.1,
            message="Step 1"
        ))
        
        await asyncio.sleep(0.1)
        
        await tracker.update(query_id, ProgressUpdate(
            stage=ProgressStage.GENERATING_SUGGESTIONS,
            progress=0.4,
            message="Step 2"
        ))
        
        # Get final progress
        progress = await tracker.get(query_id)
        
        assert progress.stage == ProgressStage.GENERATING_SUGGESTIONS
        assert progress.elapsed_seconds > 0.1
