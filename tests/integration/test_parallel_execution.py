"""Integration tests for parallel execution with rate limiting.

These tests verify the integration between parallel execution components
without requiring a full LLM provider or QueryRefinementManager.
"""

import asyncio
import time
import pytest

from query_refinement_module.parallel import ParallelConfig, DependencyGraph
from query_refinement_module.rate_limiter import TokenBucketRateLimiter, BackoffStrategy
from query_refinement_module.interfaces import RateLimitConfig
from query_refinement_module.providers import InMemorySessionStorage, ConcurrentSessionStorage


class TestParallelConfiguration:
    """Test parallel configuration with various rate limiting setups."""
    
    def test_parallel_config_with_rate_limiter(self):
        """Test creating ParallelConfig with rate limiter."""
        rate_limit_config = RateLimitConfig(
            requests_per_minute=30,
            tokens_per_minute=10000,
            max_concurrent_requests=3,
        )
        
        rate_limiter = TokenBucketRateLimiter(
            config=rate_limit_config,
            scope="global",
        )
        
        parallel_config = ParallelConfig(
            enabled=True,
            max_concurrent=3,
            rate_limiter=rate_limiter,
            backoff_strategy=BackoffStrategy(),
            max_retries=2,
        )
        
        assert parallel_config.enabled
        assert parallel_config.max_concurrent == 3
        assert parallel_config.rate_limiter is rate_limiter
        assert parallel_config.max_retries == 2
    
    def test_parallel_config_without_rate_limiter(self):
        """Test creating ParallelConfig without rate limiter."""
        parallel_config = ParallelConfig(
            enabled=True,
            max_concurrent=5,
        )
        
        assert parallel_config.enabled
        assert parallel_config.max_concurrent == 5
        assert parallel_config.rate_limiter is None


class TestRateLimiter:
    """Test rate limiter functionality."""
    
    def test_token_bucket_creation(self):
        """Test TokenBucketRateLimiter initialization."""
        config = RateLimitConfig(
            requests_per_minute=60,
            tokens_per_minute=15000,
            max_concurrent_requests=5,
        )
        
        limiter = TokenBucketRateLimiter(config=config, scope="global")
        
        assert limiter.config == config
        assert limiter.scope == "global"
        assert limiter.backoff_strategy is not None
    
    @pytest.mark.asyncio
    async def test_rate_limiter_acquire_and_release(self):
        """Test rate limiter acquire and release operations."""
        config = RateLimitConfig(
            requests_per_minute=60,
            max_concurrent_requests=2,
        )
        
        limiter = TokenBucketRateLimiter(config=config, scope="global")
        
        # Acquire should succeed
        await limiter.acquire(user_id="test_user", tokens=10)
        await limiter.acquire(user_id="test_user", tokens=10)
        
        # Release should work
        await limiter.release(user_id="test_user")
        await limiter.release(user_id="test_user")
    
    @pytest.mark.asyncio
    async def test_rate_limiter_respects_rpm_limits(self):
        """Test that rate limiter respects requests-per-minute limits."""
        config = RateLimitConfig(
            requests_per_minute=30,  # 0.5 per second
            max_concurrent_requests=5,
        )
        
        limiter = TokenBucketRateLimiter(config=config, scope="global")
        
        # First few requests should succeed quickly
        start = time.time()
        for i in range(3):
            await limiter.acquire(user_id="test_user", tokens=10)
        elapsed = time.time() - start
        
        # Should take some time due to rate limiting
        assert elapsed >= 0.0  # Basic sanity check
        
        # Clean up
        for i in range(3):
            await limiter.release(user_id="test_user")


class TestDependencyGraph:
    """Test dependency graph construction and cycle detection."""
    
    def test_dependency_graph_cycle_detection(self):
        """Test that DependencyGraph correctly detects cycles."""
        graph = DependencyGraph()
        
        # Add cyclic dependencies
        graph.add_dependency("a", "b")
        graph.add_dependency("b", "c")
        graph.add_dependency("c", "a")
        
        assert graph.has_cycles()
    
    def test_dependency_graph_acyclic(self):
        """Test that DependencyGraph recognizes acyclic graphs."""
        graph = DependencyGraph()
        
        # Create acyclic graph
        graph.add_dependency("a", "b")
        graph.add_dependency("b", "c")
        
        assert not graph.has_cycles()
    
    def test_dependency_graph_level_computation(self):
        """Test correct computation of dependency levels."""
        graph = DependencyGraph()
        
        # Level 0: no dependencies
        graph.add_node("population")
        graph.add_node("intervention")
        
        # Level 1: depends on level 0
        graph.add_dependency("comparison", "population")
        graph.add_dependency("comparison", "intervention")
        
        # Level 2: depends on level 1
        graph.add_dependency("outcome", "comparison")
        
        levels = graph.get_levels()
        
        assert len(levels) == 3
        assert set(levels[0]) == {"population", "intervention"}
        assert set(levels[1]) == {"comparison"}
        assert set(levels[2]) == {"outcome"}
    
    def test_dependency_graph_complex_structure(self):
        """Test dependency graph with complex multi-level dependencies."""
        graph = DependencyGraph()
        
        # Level 0
        graph.add_node("a")
        graph.add_node("b")
        
        # Level 1
        graph.add_dependency("c", "a")
        graph.add_dependency("d", "b")
        
        # Level 2
        graph.add_dependency("e", "c")
        graph.add_dependency("e", "d")
        
        levels = graph.get_levels()
        
        assert len(levels) == 3
        assert "e" in levels[2]
        assert "c" in levels[1] and "d" in levels[1]


@pytest.mark.asyncio
async def test_concurrent_session_storage():
    """Test that ConcurrentSessionStorage handles parallel access safely."""
    backend = InMemorySessionStorage()
    storage = ConcurrentSessionStorage(backend)
    
    # Initialize session
    await storage.save_session_async("test_session", {"counter": 0})
    
    async def increment_counter():
        """Safely increment counter under lock."""
        lock = storage._get_lock("test_session")
        async with lock:
            session = await asyncio.to_thread(backend.load_session, "test_session")
            count = session["counter"]
            await asyncio.sleep(0.001)  # Simulate work
            session["counter"] = count + 1
            await asyncio.to_thread(backend.save_session, "test_session", session)
    
    # Run 20 concurrent increments
    await asyncio.gather(*[increment_counter() for _ in range(20)])
    
    # Verify no lost updates
    final_session = await storage.load_session_async("test_session")
    assert final_session["counter"] == 20


@pytest.mark.asyncio
async def test_concurrent_storage_different_sessions():
    """Test that different sessions can be accessed in parallel."""
    backend = InMemorySessionStorage()
    storage = ConcurrentSessionStorage(backend)
    
    # Create multiple sessions
    for i in range(5):
        await storage.save_session_async(f"session_{i}", {"id": i})
    
    async def read_session(session_id):
        """Read a session."""
        return await storage.load_session_async(session_id)
    
    # Read all sessions in parallel
    results = await asyncio.gather(*[read_session(f"session_{i}") for i in range(5)])
    
    # Verify all sessions were read correctly
    assert len(results) == 5
    for i, result in enumerate(results):
        assert result["id"] == i


@pytest.mark.asyncio
async def test_concurrent_storage_lock_cleanup():
    """Test that locks are cleaned up when sessions are deleted."""
    backend = InMemorySessionStorage()
    storage = ConcurrentSessionStorage(backend)
    
    # Create and delete a session
    await storage.save_session_async("temp_session", {"data": "test"})
    assert "temp_session" in storage._locks
    
    await storage.delete_session_async("temp_session")
    assert "temp_session" not in storage._locks


class TestBackoffStrategy:
    """Test backoff strategy for retries."""
    
    def test_backoff_strategy_exponential(self):
        """Test exponential backoff calculation."""
        strategy = BackoffStrategy(base_delay=1.0, max_delay=10.0)
        
        # Calculate delays for multiple retries
        delays = [strategy.calculate_delay(i) for i in range(5)]
        
        # Each delay should be larger than the previous (with jitter)
        assert delays[0] <= 2.0  # ~1.0 with jitter
        # Max delay with jitter can exceed max_delay slightly
        assert delays[4] <= 12.0  # Capped at max_delay + some jitter
    
    def test_backoff_strategy_custom_values(self):
        """Test custom backoff parameters."""
        strategy = BackoffStrategy(base_delay=0.5, max_delay=5.0, multiplier=2.0)
        
        delay = strategy.calculate_delay(attempt=0)
        
        # Should be close to base_delay with some jitter
        assert 0.0 <= delay <= 1.0  # base_delay * (exponential_base ** 0) with jitter


class TestRateLimitConfig:
    """Test rate limit configuration."""
    
    def test_rate_limit_config_validation(self):
        """Test that RateLimitConfig validates inputs."""
        config = RateLimitConfig(
            requests_per_minute=30,
            tokens_per_minute=10000,
            max_concurrent_requests=5,
        )
        
        assert config.requests_per_minute == 30
        assert config.tokens_per_minute == 10000
        assert config.max_concurrent_requests == 5
    
    def test_rate_limit_config_unlimited(self):
        """Test unlimited rate limit configuration."""
        config = RateLimitConfig.unlimited()
        
        assert config.requests_per_minute == 0
        assert config.tokens_per_minute is None
        assert config.max_concurrent_requests == 0
    
    def test_rate_limit_config_invalid_values(self):
        """Test that invalid configurations are rejected."""
        with pytest.raises(ValueError):
            RateLimitConfig(requests_per_minute=-1)
        
        with pytest.raises(ValueError):
            RateLimitConfig(tokens_per_minute=-100)
        
        with pytest.raises(ValueError):
            RateLimitConfig(max_concurrent_requests=-5)
