"""
Parallel processing infrastructure for LLM query refinement.

Provides:
- ParallelQueryAnalyzer: Orchestrates parallel LLM calls with dependency management and rate limiting.
- DependencyGraph: Models dependencies between queries/prompts for correct execution order.
- ParallelConfig: Configures parallelism (max workers, batching, etc).

Integrates with rate limiting and provider interfaces.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING

from .interfaces import QueryAnalyzerInterface, LLMProviderInterface
from .rate_limiter import RateLimiterInterface, BackoffStrategy, RateLimitExceeded

if TYPE_CHECKING:
    from .interfaces import AspectAnalysisResult
    from .schema import RefinementAspect

logger = logging.getLogger(__name__)


@dataclass
class ParallelConfig:
    """
    Configuration for parallel query execution.
    
    Attributes:
        enabled: Enable parallel execution (False = sequential fallback).
        max_concurrent: Maximum concurrent LLM calls per level.
        rate_limiter: Optional rate limiter for API throttling.
        backoff_strategy: Backoff strategy for retries on rate limit errors.
        max_retries: Maximum retry attempts for rate-limited calls.
    """
    enabled: bool = True
    max_concurrent: int = 8
    rate_limiter: Optional[RateLimiterInterface] = None
    backoff_strategy: BackoffStrategy = None
    max_retries: int = 3
    
    def __post_init__(self):
        if self.backoff_strategy is None:
            self.backoff_strategy = BackoffStrategy()


class DependencyGraph:
    """
    Models dependencies between queries/prompts for correct execution order.
    
    Computes dependency levels:
    - Level 0: Aspects with no dependencies
    - Level 1: Aspects depending only on Level 0
    - Level N: Aspects depending on levels 0..N-1
    """
    
    def __init__(self):
        self.graph: Dict[str, Set[str]] = {}  # aspect_id -> set of dependency aspect_ids
        self._levels: Optional[List[List[str]]] = None
        self._level_map: Optional[Dict[str, int]] = None
    
    def add_node(self, node: str) -> None:
        """Add a node (aspect) to the graph."""
        if node not in self.graph:
            self.graph[node] = set()
            self._invalidate_cache()
    
    def add_dependency(self, node: str, depends_on: str) -> None:
        """Add a dependency: node depends on depends_on."""
        self.add_node(node)
        self.add_node(depends_on)
        self.graph[node].add(depends_on)
        self._invalidate_cache()
    
    def _invalidate_cache(self) -> None:
        """Invalidate cached level computations."""
        self._levels = None
        self._level_map = None
    
    def has_cycles(self) -> bool:
        """Check if the graph has cycles using DFS."""
        visited = set()
        rec_stack = set()
        
        def visit(node: str) -> bool:
            if node in rec_stack:
                return True  # Cycle detected
            if node in visited:
                return False
            
            visited.add(node)
            rec_stack.add(node)
            
            for dep in self.graph.get(node, set()):
                if visit(dep):
                    return True
            
            rec_stack.remove(node)
            return False
        
        for node in self.graph:
            if visit(node):
                return True
        return False
    
    def get_levels(self) -> List[List[str]]:
        """
        Compute dependency levels for parallel execution.
        
        Returns:
            List of levels, where each level is a list of aspect IDs that can be
            executed in parallel (all dependencies are in earlier levels).
        
        Raises:
            RuntimeError: If the graph contains cycles.
        """
        if self._levels is not None:
            return self._levels
        
        if self.has_cycles():
            raise RuntimeError("Dependency graph contains cycles - cannot compute levels")
        
        # Compute levels using level-by-level traversal
        levels: List[List[str]] = []
        processed = set()
        
        while len(processed) < len(self.graph):
            # Find all nodes with no unprocessed dependencies
            current_level = [
                node for node in self.graph
                if node not in processed and all(dep in processed for dep in self.graph[node])
            ]
            
            if not current_level:
                # Should not happen if has_cycles() returned False
                raise RuntimeError("Unable to compute levels - possible graph error")
            
            levels.append(current_level)
            processed.update(current_level)
        
        self._levels = levels
        
        # Build level map for quick lookup
        self._level_map = {}
        for level_idx, level_nodes in enumerate(levels):
            for node in level_nodes:
                self._level_map[node] = level_idx
        
        logger.debug(
            "Computed %d dependency levels: %s",
            len(levels),
            {f"L{i}": nodes for i, nodes in enumerate(levels)}
        )
        
        return levels
    
    def get_level_for_node(self, node: str) -> int:
        """Get the dependency level for a specific node."""
        if self._level_map is None:
            self.get_levels()
        return self._level_map.get(node, -1)


class ParallelQueryAnalyzer:
    """
    Orchestrates parallel LLM calls with dependency management and rate limiting.
    
    Wraps a QueryAnalyzerInterface to provide parallel execution while maintaining
    dependency order. Executes aspects level-by-level (sequentially), with aspects
    within each level executed in parallel.
    
    Features:
    - Dependency-aware parallel execution using DependencyGraph
    - Rate limiting integration with exponential backoff
    - Automatic fallback to sequential on errors or cycles
    - Detailed tracing and error handling
    """
    
    def __init__(
        self,
        query_analyzer: QueryAnalyzerInterface,
        config: ParallelConfig,
        trace_emitter: Optional[Any] = None
    ):
        """
        Initialize parallel query analyzer.
        
        Args:
            query_analyzer: Underlying analyzer for aspect analysis.
            config: Parallel execution configuration.
            trace_emitter: Optional trace emitter for instrumentation.
        """
        self.query_analyzer = query_analyzer
        self.config = config
        self.trace_emitter = trace_emitter
    
    async def analyze_aspects_parallel(
        self,
        query: str,
        aspects: List["RefinementAspect"],
        llm_provider: LLMProviderInterface,
        dependency_context_provider: Callable[[str], Dict[str, str]],
        user_id: Optional[str] = None
    ) -> Dict[str, "AspectAnalysisResult"]:
        """
        Analyze multiple aspects in parallel, respecting dependencies.
        
        Executes aspects level-by-level:
        - Level 0 (no dependencies): all in parallel
        - Level 1 (depends on L0): all in parallel after L0 completes
        - etc.
        
        Args:
            query: Original query to analyze.
            aspects: List of refinement aspects to analyze.
            llm_provider: LLM provider for analysis.
            dependency_context_provider: Function to get dependency context for an aspect_id.
            user_id: Optional user ID for rate limiting.
        
        Returns:
            Dict mapping aspect_id to AspectAnalysisResult.
        """
        start_time = time.time()
        
        if self.trace_emitter:
            self.trace_emitter.emit(
                "parallel_execution_start",
                metadata={
                    "num_aspects": len(aspects),
                    "max_concurrent": self.config.max_concurrent,
                }
            )
        
        # Build dependency graph
        dep_graph = DependencyGraph()
        aspect_map = {aspect.id: aspect for aspect in aspects}
        
        for aspect in aspects:
            dep_graph.add_node(aspect.id)
            if aspect.depends_on:
                for dep_id in aspect.depends_on:
                    dep_graph.add_dependency(aspect.id, dep_id)
        
        # Check for cycles - fallback to sequential if found
        if dep_graph.has_cycles():
            logger.warning("Dependency graph has cycles - falling back to sequential execution")
            if self.trace_emitter:
                self.trace_emitter.emit(
                    "parallel_execution_fallback",
                    metadata={"reason": "cycles_detected"}
                )
            return await self._analyze_sequential(
                query, aspects, llm_provider, dependency_context_provider, user_id
            )
        
        # Get dependency levels
        try:
            levels = dep_graph.get_levels()
        except RuntimeError as e:
            logger.error("Failed to compute dependency levels: %s", e)
            if self.trace_emitter:
                self.trace_emitter.emit(
                    "parallel_execution_fallback",
                    metadata={"reason": "level_computation_failed", "error": str(e)}
                )
            return await self._analyze_sequential(
                query, aspects, llm_provider, dependency_context_provider, user_id
            )
        
        # Execute level-by-level
        results: Dict[str, AspectAnalysisResult] = {}
        
        for level_idx, level_aspect_ids in enumerate(levels):
            if self.trace_emitter:
                self.trace_emitter.emit(
                    "level_execution_start",
                    metadata={
                        "level": level_idx,
                        "num_aspects": len(level_aspect_ids),
                        "aspect_ids": level_aspect_ids,
                    }
                )
            
            logger.debug(
                "Executing dependency level %d with %d aspects: %s",
                level_idx,
                len(level_aspect_ids),
                level_aspect_ids
            )
            
            # Execute all aspects in this level in parallel
            level_results = await self._execute_level(
                query=query,
                aspect_ids=level_aspect_ids,
                aspect_map=aspect_map,
                llm_provider=llm_provider,
                dependency_context_provider=dependency_context_provider,
                user_id=user_id
            )
            
            results.update(level_results)
            
            if self.trace_emitter:
                self.trace_emitter.emit(
                    "level_execution_complete",
                    metadata={
                        "level": level_idx,
                        "num_completed": len(level_results),
                        "num_failed": len([r for r in level_results.values() if r is None]),
                    }
                )
        
        if self.trace_emitter:
            execution_time = time.time() - start_time
            num_successful = len([r for r in results.values() if r is not None])
            
            self.trace_emitter.emit(
                "parallel_execution_complete",
                metadata={
                    "total_aspects": len(aspects),
                    "num_levels": len(levels),
                    "num_successful": num_successful,
                    "execution_time_seconds": execution_time,
                }
            )
            
            # Emit metrics for monitoring
            if hasattr(self.trace_emitter, 'metric'):
                self.trace_emitter.metric(
                    "parallel.execution_time",
                    execution_time,
                    unit="seconds",
                    metadata={
                        "num_aspects": len(aspects),
                        "num_levels": len(levels),
                    }
                )
                
                self.trace_emitter.metric(
                    "parallel.success_rate",
                    num_successful / len(aspects) * 100 if aspects else 0,
                    unit="percent",
                    metadata={"total_aspects": len(aspects)}
                )
                
                # Estimate parallelism efficiency (vs sequential)
                # Sequential would take sum of all level times; parallel takes max within each level
                if len(levels) > 0:
                    parallelism_factor = len(aspects) / len(levels) if len(levels) > 0 else 1
                    self.trace_emitter.metric(
                        "parallel.avg_concurrency",
                        parallelism_factor,
                        unit="aspects/level",
                        metadata={"num_levels": len(levels)}
                    )
        
        return results
    
    async def _execute_level(
        self,
        query: str,
        aspect_ids: List[str],
        aspect_map: Dict[str, "RefinementAspect"],
        llm_provider: LLMProviderInterface,
        dependency_context_provider: Callable[[str], Dict[str, str]],
        user_id: Optional[str] = None
    ) -> Dict[str, "AspectAnalysisResult"]:
        """Execute all aspects in a single dependency level in parallel."""
        
        # Create tasks for all aspects in this level
        tasks = [
            self._analyze_aspect_with_retry(
                query=query,
                aspect=aspect_map[aspect_id],
                llm_provider=llm_provider,
                dependency_context_provider=dependency_context_provider,
                user_id=user_id
            )
            for aspect_id in aspect_ids
        ]
        
        # Execute in parallel with return_exceptions=True to handle individual failures
        task_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Map results back to aspect IDs
        results = {}
        for aspect_id, result in zip(aspect_ids, task_results):
            if isinstance(result, Exception):
                logger.error(
                    "Failed to analyze aspect %s: %s",
                    aspect_id,
                    result,
                    exc_info=result
                )
                results[aspect_id] = None  # Mark as failed
            else:
                results[aspect_id] = result
        
        return results
    
    async def _analyze_aspect_with_retry(
        self,
        query: str,
        aspect: "RefinementAspect",
        llm_provider: LLMProviderInterface,
        dependency_context_provider: Callable[[str], Dict[str, str]],
        user_id: Optional[str] = None
    ) -> "AspectAnalysisResult":
        """
        Analyze a single aspect with rate limiting and retry logic.
        
        Implements exponential backoff for rate limit errors.
        """
        last_error = None
        
        for attempt in range(self.config.max_retries):
            try:
                # Acquire rate limit permission
                if self.config.rate_limiter:
                    await self.config.rate_limiter.acquire(user_id=user_id, tokens=1)
                
                try:
                    # Get dependency context
                    dependency_context = dependency_context_provider(aspect.id)
                    
                    # Analyze aspect (this is the actual LLM call)
                    result = self.query_analyzer.analyze_aspect(
                        query=query,
                        aspect=aspect,
                        dependency_context=dependency_context,
                        llm_provider=llm_provider
                    )
                    
                    return result
                
                finally:
                    # Release rate limit
                    if self.config.rate_limiter:
                        await self.config.rate_limiter.release(user_id=user_id, tokens=1)
            
            except RateLimitExceeded as e:
                last_error = e
                
                # Calculate backoff delay
                delay = self.config.backoff_strategy.calculate_delay(attempt)
                
                logger.warning(
                    "Rate limit exceeded for aspect %s (attempt %d/%d), retrying in %.2fs",
                    aspect.id,
                    attempt + 1,
                    self.config.max_retries,
                    delay
                )
                
                if self.trace_emitter:
                    self.trace_emitter.emit(
                        "aspect_rate_limit_retry",
                        metadata={
                            "aspect_id": aspect.id,
                            "attempt": attempt + 1,
                            "max_retries": self.config.max_retries,
                            "delay": delay,
                            "retry_after": e.retry_after,
                        }
                    )
                
                # Wait before retry
                await asyncio.sleep(delay)
            
            except Exception as e:
                # Non-rate-limit errors are not retried
                logger.error(
                    "Failed to analyze aspect %s: %s",
                    aspect.id,
                    e,
                    exc_info=True
                )
                raise
        
        # Max retries exceeded
        logger.error(
            "Max retries exceeded for aspect %s after %d attempts",
            aspect.id,
            self.config.max_retries
        )
        raise last_error or RuntimeError(f"Failed to analyze aspect {aspect.id}")
    
    async def _analyze_sequential(
        self,
        query: str,
        aspects: List["RefinementAspect"],
        llm_provider: LLMProviderInterface,
        dependency_context_provider: Callable[[str], Dict[str, str]],
        user_id: Optional[str] = None
    ) -> Dict[str, "AspectAnalysisResult"]:
        """Fallback to sequential execution (same as original initialize() logic)."""
        results = {}
        
        for aspect in aspects:
            try:
                dependency_context = dependency_context_provider(aspect.id)
                result = self.query_analyzer.analyze_aspect(
                    query=query,
                    aspect=aspect,
                    dependency_context=dependency_context,
                    llm_provider=llm_provider
                )
                results[aspect.id] = result
            except Exception as e:
                logger.error(
                    "Failed to analyze aspect %s: %s",
                    aspect.id,
                    e,
                    exc_info=True
                )
                results[aspect.id] = None
        
        return results


__all__ = [
    "ParallelConfig",
    "DependencyGraph",
    "ParallelQueryAnalyzer",
]
