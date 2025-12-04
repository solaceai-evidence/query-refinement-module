"""
Unit tests for parallel processing infrastructure.

Tests for ParallelConfig, DependencyGraph, and ParallelQueryAnalyzer.
"""

import pytest
from query_refinement_module.parallel import ParallelConfig, DependencyGraph


class TestParallelConfig:
    """Test ParallelConfig dataclass and defaults."""
    
    def test_default_config(self):
        """Test default parallel configuration."""
        config = ParallelConfig()
        
        assert config.enabled is True
        assert config.max_concurrent == 8
        assert config.rate_limiter is None
        assert config.backoff_strategy is not None  # Auto-initialized
        assert config.max_retries == 3
    
    def test_custom_config(self):
        """Test custom parallel configuration."""
        config = ParallelConfig(
            enabled=False,
            max_concurrent=4,
            max_retries=5
        )
        
        assert config.enabled is False
        assert config.max_concurrent == 4
        assert config.max_retries == 5


class TestDependencyGraph:
    """Test dependency graph construction and level computation."""
    
    def test_empty_graph(self):
        """Test empty dependency graph."""
        graph = DependencyGraph()
        assert graph.graph == {}
        assert graph.get_levels() == []
    
    def test_single_node_no_dependencies(self):
        """Test graph with single node and no dependencies."""
        graph = DependencyGraph()
        graph.add_node("A")
        
        levels = graph.get_levels()
        assert len(levels) == 1
        assert levels[0] == ["A"]
    
    def test_linear_dependencies(self):
        """Test linear dependency chain: A -> B -> C."""
        graph = DependencyGraph()
        graph.add_node("A")
        graph.add_dependency("B", "A")
        graph.add_dependency("C", "B")
        
        levels = graph.get_levels()
        assert len(levels) == 3
        assert levels[0] == ["A"]
        assert levels[1] == ["B"]
        assert levels[2] == ["C"]
    
    def test_parallel_dependencies(self):
        """Test parallel dependencies: B and C both depend on A."""
        graph = DependencyGraph()
        graph.add_node("A")
        graph.add_dependency("B", "A")
        graph.add_dependency("C", "A")
        
        levels = graph.get_levels()
        assert len(levels) == 2
        assert levels[0] == ["A"]
        assert set(levels[1]) == {"B", "C"}
    
    def test_diamond_dependencies(self):
        """Test diamond dependency: D depends on B and C, both depend on A."""
        graph = DependencyGraph()
        graph.add_node("A")
        graph.add_dependency("B", "A")
        graph.add_dependency("C", "A")
        graph.add_dependency("D", "B")
        graph.add_dependency("D", "C")
        
        levels = graph.get_levels()
        assert len(levels) == 3
        assert levels[0] == ["A"]
        assert set(levels[1]) == {"B", "C"}
        assert levels[2] == ["D"]
    
    def test_cycle_detection(self):
        """Test cycle detection: A -> B -> C -> A."""
        graph = DependencyGraph()
        graph.add_dependency("A", "B")
        graph.add_dependency("B", "C")
        graph.add_dependency("C", "A")
        
        assert graph.has_cycles() is True
        
        with pytest.raises(RuntimeError, match="cycles"):
            graph.get_levels()
    
    def test_self_dependency_cycle(self):
        """Test self-dependency cycle: A -> A."""
        graph = DependencyGraph()
        graph.add_dependency("A", "A")
        
        assert graph.has_cycles() is True
    
    def test_complex_graph(self):
        """Test complex dependency graph with multiple levels."""
        graph = DependencyGraph()
        
        # Level 0: A, B (no dependencies)
        graph.add_node("A")
        graph.add_node("B")
        
        # Level 1: C depends on A, D depends on B
        graph.add_dependency("C", "A")
        graph.add_dependency("D", "B")
        
        # Level 2: E depends on C and D
        graph.add_dependency("E", "C")
        graph.add_dependency("E", "D")
        
        # Level 3: F depends on E
        graph.add_dependency("F", "E")
        
        levels = graph.get_levels()
        assert len(levels) == 4
        assert set(levels[0]) == {"A", "B"}
        assert set(levels[1]) == {"C", "D"}
        assert levels[2] == ["E"]
        assert levels[3] == ["F"]
    
    def test_get_level_for_node(self):
        """Test getting level index for specific nodes."""
        graph = DependencyGraph()
        graph.add_node("A")
        graph.add_dependency("B", "A")
        graph.add_dependency("C", "B")
        
        # Trigger level computation
        graph.get_levels()
        
        assert graph.get_level_for_node("A") == 0
        assert graph.get_level_for_node("B") == 1
        assert graph.get_level_for_node("C") == 2
        assert graph.get_level_for_node("nonexistent") == -1


class TestDependencyGraphCaching:
    """Test dependency graph level computation caching."""
    
    def test_level_caching(self):
        """Test that levels are cached after first computation."""
        graph = DependencyGraph()
        graph.add_node("A")
        graph.add_dependency("B", "A")
        
        levels1 = graph.get_levels()
        levels2 = graph.get_levels()
        
        # Should return same object (cached)
        assert levels1 is levels2
    
    def test_cache_invalidation(self):
        """Test that cache is invalidated when graph changes."""
        graph = DependencyGraph()
        graph.add_node("A")
        
        levels1 = graph.get_levels()
        assert len(levels1) == 1
        
        # Add dependency - should invalidate cache
        graph.add_dependency("B", "A")
        
        levels2 = graph.get_levels()
        assert len(levels2) == 2
        # New computation, not cached
        assert levels1 is not levels2
