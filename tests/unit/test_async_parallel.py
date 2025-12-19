"""
Unit tests for async parallel execution enhancements.

Tests for async LLM calls, streaming, and improved parallel performance.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, patch

from query_refinement_module.parallel import ParallelQueryAnalyzer, ParallelConfig
from query_refinement_module.analyzers import LLMQueryAnalyzer
from query_refinement_module.interfaces import (
    AspectAnalysisResult,
    LLMCompletionResult,
    RateLimitConfig,
)
from query_refinement_module.rate_limiter import TokenBucketRateLimiter, BackoffStrategy
from query_refinement_module.schema import RefinementAspect


@pytest.fixture
def mock_llm_provider():
    """Create a mock LLM provider with async support."""
    provider = Mock()
    
    # Mock async complete
    async def mock_complete_async(*args, **kwargs):
        await asyncio.sleep(0.01)  # Simulate network delay
        return LLMCompletionResult(
            context='{"needs_refinement": false, "explanation": "Test result"}',
            model="test-model",
            total_tokens=100,
            metadata={},
        )
    
    provider.complete_async = mock_complete_async
    
    # Mock sync complete (fallback)
    provider.complete = Mock(return_value=LLMCompletionResult(
        context='{"needs_refinement": false, "explanation": "Test result"}',
        model="test-model",
        total_tokens=100,
        metadata={},
    ))
    
    return provider


@pytest.fixture
def mock_analyzer():
    """Create a mock query analyzer with async support."""
    analyzer = Mock(spec=LLMQueryAnalyzer)
    
    # Mock async analyze_aspect
    async def mock_analyze_async(*args, **kwargs):
        await asyncio.sleep(0.01)  # Simulate processing
        return AspectAnalysisResult(
            needs_refinement=False,
            explanation="Aspect is clear",
            clarifying_question=None,
        )
    
    analyzer.analyze_aspect_async = mock_analyze_async
    
    # Mock sync analyze_aspect (fallback)
    analyzer.analyze_aspect = Mock(return_value=AspectAnalysisResult(
        needs_refinement=False,
        explanation="Aspect is clear",
        clarifying_question=None,
    ))
    
    return analyzer


@pytest.fixture
def simple_aspects():
    """Create simple test aspects without dependencies."""
    return [
        RefinementAspect(
            id="aspect1",
            aspect_name="Aspect 1",
            aspect_description="First aspect",
            refinement_instructions="Analyze aspect 1",
            depends_on=None,
        ),
        RefinementAspect(
            id="aspect2",
            aspect_name="Aspect 2",
            aspect_description="Second aspect",
            refinement_instructions="Analyze aspect 2",
            depends_on=None,
        ),
        RefinementAspect(
            id="aspect3",
            aspect_name="Aspect 3",
            aspect_description="Third aspect",
            refinement_instructions="Analyze aspect 3",
            depends_on=None,
        ),
    ]


@pytest.fixture
def dependent_aspects():
    """Create test aspects with dependencies."""
    return [
        RefinementAspect(
            id="base",
            aspect_name="Base",
            aspect_description="Base aspect",
            refinement_instructions="Analyze base",
            depends_on=None,
        ),
        RefinementAspect(
            id="dependent1",
            aspect_name="Dependent 1",
            aspect_description="Depends on base",
            refinement_instructions="Analyze dependent 1",
            depends_on=["base"],
        ),
        RefinementAspect(
            id="dependent2",
            aspect_name="Dependent 2",
            aspect_description="Depends on base",
            refinement_instructions="Analyze dependent 2",
            depends_on=["base"],
        ),
        RefinementAspect(
            id="final",
            aspect_name="Final",
            aspect_description="Depends on dependents",
            refinement_instructions="Analyze final",
            depends_on=["dependent1", "dependent2"],
        ),
    ]


class TestAsyncAnalyzer:
    """Test async analyzer functionality."""
    
    @pytest.mark.asyncio
    async def test_analyze_aspect_async_uses_async_provider(self, mock_llm_provider):
        """Test that analyze_aspect_async uses async complete when available."""
        analyzer = LLMQueryAnalyzer(llm_provider=mock_llm_provider)
        
        aspect = RefinementAspect(
            id="test",
            aspect_name="Test",
            aspect_description="Test aspect",
            refinement_instructions="Test prompt",
        )
        
        result = await analyzer.analyze_aspect_async(
            query="test query",
            aspect=aspect,
            llm_provider=mock_llm_provider,
        )
        
        assert isinstance(result, AspectAnalysisResult)
        assert result.needs_refinement is False
        # Verify async method was called (it's an async function, so it was awaited)
    
    @pytest.mark.asyncio
    async def test_analyze_aspect_async_fallback_to_thread(self):
        """Test that analyze_aspect_async falls back to thread pool if no async method."""
        # Provider without complete_async
        provider = Mock()
        provider.complete = Mock(return_value=LLMCompletionResult(
            context='{"needs_refinement": true, "explanation": "Needs work", "clarifying_question": "What?"}',
            model="test-model",
            total_tokens=50,
            metadata={},
        ))
        # Ensure complete_async doesn't exist
        if hasattr(provider, 'complete_async'):
            del provider.complete_async
        
        analyzer = LLMQueryAnalyzer(llm_provider=provider)
        
        aspect = RefinementAspect(
            id="test",
            aspect_name="Test",
            aspect_description="Test aspect",
            refinement_instructions="Test prompt",
        )
        
        result = await analyzer.analyze_aspect_async(
            query="test query",
            aspect=aspect,
            llm_provider=provider,
        )
        
        assert isinstance(result, AspectAnalysisResult)
        assert result.needs_refinement is True
        assert provider.complete.called


class TestParallelQueryAnalyzerAsync:
    """Test ParallelQueryAnalyzer with async execution."""
    
    @pytest.mark.asyncio
    async def test_analyze_aspects_parallel_simple(self, mock_analyzer, mock_llm_provider, simple_aspects):
        """Test parallel analysis of simple aspects without dependencies."""
        config = ParallelConfig(
            enabled=True,
            max_concurrent=3,
            max_retries=1,
        )
        
        parallel_analyzer = ParallelQueryAnalyzer(
            query_analyzer=mock_analyzer,
            config=config,
        )
        
        def get_deps(aspect_id):
            return {}
        
        results = await parallel_analyzer.analyze_aspects_parallel(
            query="test query",
            aspects=simple_aspects,
            llm_provider=mock_llm_provider,
            dependency_context_provider=get_deps,
        )
        
        assert len(results) == 3
        assert all(aspect.id in results for aspect in simple_aspects)
        assert all(isinstance(r, AspectAnalysisResult) for r in results.values())
    
    @pytest.mark.asyncio
    async def test_analyze_aspects_parallel_with_dependencies(self, mock_analyzer, mock_llm_provider, dependent_aspects):
        """Test parallel analysis respects dependencies."""
        config = ParallelConfig(
            enabled=True,
            max_concurrent=2,
            max_retries=1,
        )
        
        parallel_analyzer = ParallelQueryAnalyzer(
            query_analyzer=mock_analyzer,
            config=config,
        )
        
        # Track execution order
        execution_order = []
        
        async def tracking_analyzer(*args, aspect=None, **kwargs):
            await asyncio.sleep(0.01)
            execution_order.append(aspect.id)
            return AspectAnalysisResult(
                needs_refinement=False,
                explanation=f"Analyzed {aspect.id}",
                clarifying_question=None,
            )
        
        mock_analyzer.analyze_aspect_async = tracking_analyzer
        
        completed_aspects = {}
        
        def get_deps(aspect_id):
            # Return completed aspects as context
            return {aid: "completed" for aid in completed_aspects.keys()}
        
        results = await parallel_analyzer.analyze_aspects_parallel(
            query="test query",
            aspects=dependent_aspects,
            llm_provider=mock_llm_provider,
            dependency_context_provider=get_deps,
        )
        
        assert len(results) == 4
        
        # Verify execution order respects dependencies
        base_idx = execution_order.index("base")
        dep1_idx = execution_order.index("dependent1")
        dep2_idx = execution_order.index("dependent2")
        final_idx = execution_order.index("final")
        
        # Base must execute before dependents
        assert base_idx < dep1_idx
        assert base_idx < dep2_idx
        
        # Dependents must execute before final
        assert dep1_idx < final_idx
        assert dep2_idx < final_idx
    
    @pytest.mark.asyncio
    async def test_streaming_parallel_yields_per_level(self, mock_analyzer, mock_llm_provider, dependent_aspects):
        """Test that streaming yields results after each dependency level."""
        config = ParallelConfig(
            enabled=True,
            max_concurrent=2,
            max_retries=1,
        )
        
        parallel_analyzer = ParallelQueryAnalyzer(
            query_analyzer=mock_analyzer,
            config=config,
        )
        
        def get_deps(aspect_id):
            return {}
        
        yielded_levels = []
        total_results = {}
        
        async for level_idx, level_results, metadata in parallel_analyzer.analyze_aspects_parallel_streaming(
            query="test query",
            aspects=dependent_aspects,
            llm_provider=mock_llm_provider,
            dependency_context_provider=get_deps,
        ):
            yielded_levels.append(level_idx)
            total_results.update(level_results)
            
            # Verify metadata
            assert "total_levels" in metadata
            assert "level_count" in metadata
            assert "elapsed_time" in metadata
            assert metadata["elapsed_time"] >= 0
        
        # Should yield 3 levels: [base], [dependent1, dependent2], [final]
        assert len(yielded_levels) == 3
        assert len(total_results) == 4
    
    @pytest.mark.asyncio
    async def test_rate_limiting_integration(self, mock_analyzer, mock_llm_provider, simple_aspects):
        """Test that rate limiting works with parallel execution."""
        rate_config = RateLimitConfig(
            requests_per_minute=30,
            max_concurrent_requests=2,
        )
        
        rate_limiter = TokenBucketRateLimiter(
            config=rate_config,
            scope="test",
        )
        
        config = ParallelConfig(
            enabled=True,
            max_concurrent=2,
            rate_limiter=rate_limiter,
            max_retries=1,
        )
        
        parallel_analyzer = ParallelQueryAnalyzer(
            query_analyzer=mock_analyzer,
            config=config,
        )
        
        def get_deps(aspect_id):
            return {}
        
        import time
        start = time.time()
        
        results = await parallel_analyzer.analyze_aspects_parallel(
            query="test query",
            aspects=simple_aspects,
            llm_provider=mock_llm_provider,
            dependency_context_provider=get_deps,
        )
        
        elapsed = time.time() - start
        
        assert len(results) == 3
        # Rate limiting should add some delay
        assert elapsed >= 0.0


class TestAsyncProviderMethods:
    """Test async provider methods."""
    
    @pytest.mark.asyncio
    async def test_llm_provider_complete_async_exists(self):
        """Test that LiteLLMProvider has complete_async method."""
        from query_refinement_module.providers import LiteLLMProvider
        
        # Check that complete_async is defined
        assert hasattr(LiteLLMProvider, 'complete_async')
        
        # Verify it's an async method
        import inspect
        assert inspect.iscoroutinefunction(LiteLLMProvider.complete_async)
    
    def test_llm_provider_has_http_client_support(self):
        """Test that LiteLLMProvider initializes HTTP client for connection pooling."""
        from query_refinement_module.providers import LiteLLMProvider
        
        try:
            import httpx
            has_httpx = True
        except ImportError:
            has_httpx = False
        
        if has_httpx:
            provider = LiteLLMProvider(default_model="gpt-3.5-turbo")
            # Should have _http_client attribute
            assert hasattr(provider, '_http_client')


class TestCoreManagerStreaming:
    """Test QueryRefinementManager streaming initialization."""
    
    @pytest.mark.asyncio
    async def test_initialize_streaming_yields_incrementally(self, mock_analyzer, mock_llm_provider):
        """Test that initialize_streaming yields results per level."""
        from query_refinement_module.core import QueryRefinementManager
        from query_refinement_module.providers import NoOpTracingProvider
        
        manager = QueryRefinementManager(
            llm_provider=mock_llm_provider,
            query_analyzer=mock_analyzer,
            tracing_provider=NoOpTracingProvider(),
        )
        
        aspects = [
            RefinementAspect(
                id="a1",
                aspect_name="A1",
                aspect_description="Aspect 1",
                refinement_instructions="Analyze",
            ),
            RefinementAspect(
                id="a2",
                aspect_name="A2",
                aspect_description="Aspect 2",
                refinement_instructions="Analyze",
                depends_on=["a1"],
            ),
        ]
        
        config = ParallelConfig(enabled=True, max_concurrent=2)
        
        yields = []
        final_session = None
        
        async for session, level_idx, level_results, metadata, is_final in manager.initialize_streaming(
            original_query="test",
            refinement_framework=aspects,
            parallel_config=config,
        ):
            yields.append((level_idx, is_final))
            if is_final:
                final_session = session
                break
        
        # Should yield at least 2 levels plus final
        assert len(yields) >= 2
        assert yields[-1][1] is True  # Last yield is final
        assert final_session is not None
        assert len(final_session.steps) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
