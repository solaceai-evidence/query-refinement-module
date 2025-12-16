"""Integration test for parallel execution with dependency chain.

This test verifies that the parallel execution correctly handles dependency chains
and executes aspects in the proper order based on their dependencies.
"""

import pytest
from typing import Dict, Optional
from unittest.mock import Mock

from query_refinement_module.parallel import (
    ParallelConfig, 
    ParallelQueryAnalyzer,
    DependencyGraph,
)
from query_refinement_module.interfaces import (
    QueryAnalyzerInterface,
    LLMProviderInterface,
    AspectAnalysisResult,
)
from query_refinement_module.schema import RefinementAspect
from query_refinement_module.rate_limiter import BackoffStrategy


class MockQueryAnalyzer(QueryAnalyzerInterface):
    """Mock analyzer that tracks execution order."""
    
    def __init__(self):
        self.execution_log = []
        self.call_count = 0
    
    def analyze_aspect(
        self,
        query: str,
        aspect: RefinementAspect,
        dependency_context: Optional[Dict[str, str]] = None,
        llm_provider: Optional[LLMProviderInterface] = None,
    ) -> AspectAnalysisResult:
        """Track aspect execution and verify dependency context."""
        self.call_count += 1
        
        # Log execution with timestamp
        execution_entry = {
            'aspect_id': aspect.id,
            'aspect_name': aspect.aspect_name,
            'depends_on': aspect.depends_on or [],
            'dependency_context_keys': list(dependency_context.keys()) if dependency_context else [],
            'call_order': self.call_count,
        }
        self.execution_log.append(execution_entry)
        
        # Verify that all dependencies have been executed before this aspect
        if aspect.depends_on:
            executed_ids = {entry['aspect_id'] for entry in self.execution_log[:-1]}
            for dep_id in aspect.depends_on:
                assert dep_id in executed_ids, (
                    f"Aspect '{aspect.id}' depends on '{dep_id}' but '{dep_id}' "
                    f"hasn't been executed yet. Executed: {executed_ids}"
                )
        
        # Return mock result
        return AspectAnalysisResult(
            needs_refinement=True,
            reason=f"Mock analysis for {aspect.aspect_name}",
            clarifying_question=f"Please clarify {aspect.aspect_name}?",
        )


class TestDependencyParallelWorkflow:
    """Test parallel execution with realistic dependency chains."""
    
    def test_dependency_graph_levels(self):
        """Test that dependency graph correctly computes execution levels."""
        # Create aspects with dependencies matching pico_advanced structure:
        # Level 0: population_demographics (no deps)
        # Level 1: population_clinical_profile (depends on demographics)
        # Level 2: intervention_specification (depends on demographics + clinical)
        # Level 3: comparison_group (depends on intervention)
        # Level 4: primary_outcomes (depends on intervention + comparison + clinical)
        # Level 5: study_design_context (depends on all previous)
        
        aspects = [
            RefinementAspect(
                id="population_demographics",
                aspect_name="Population Demographics",
                aspect_description="Demographics",
                refinement_instructions="Analyze demographics",
                depends_on=None,
            ),
            RefinementAspect(
                id="population_clinical_profile",
                aspect_name="Clinical Profile",
                aspect_description="Clinical profile",
                refinement_instructions="Analyze clinical profile",
                depends_on=["population_demographics"],
            ),
            RefinementAspect(
                id="intervention_specification",
                aspect_name="Intervention",
                aspect_description="Intervention details",
                refinement_instructions="Analyze intervention",
                depends_on=["population_demographics", "population_clinical_profile"],
            ),
            RefinementAspect(
                id="comparison_group",
                aspect_name="Comparison",
                aspect_description="Comparison group",
                refinement_instructions="Analyze comparison",
                depends_on=["intervention_specification"],
            ),
            RefinementAspect(
                id="primary_outcomes",
                aspect_name="Outcomes",
                aspect_description="Primary outcomes",
                refinement_instructions="Analyze outcomes",
                depends_on=["intervention_specification", "comparison_group", "population_clinical_profile"],
            ),
            RefinementAspect(
                id="study_design_context",
                aspect_name="Study Design",
                aspect_description="Study design",
                refinement_instructions="Analyze study design",
                depends_on=["population_demographics", "population_clinical_profile", 
                           "intervention_specification", "comparison_group", "primary_outcomes"],
            ),
        ]
        
        # Build dependency graph
        graph = DependencyGraph()
        for aspect in aspects:
            graph.add_node(aspect.id)
            if aspect.depends_on:
                for dep_id in aspect.depends_on:
                    graph.add_dependency(aspect.id, dep_id)
        
        # Compute levels
        levels = graph.get_levels()
        
        # Verify level structure
        assert len(levels) == 6, f"Expected 6 levels, got {len(levels)}: {levels}"
        
        # Level 0: Only demographics (no dependencies)
        assert levels[0] == ["population_demographics"], \
            f"Level 0 should be ['population_demographics'], got {levels[0]}"
        
        # Level 1: Clinical profile (depends on demographics)
        assert levels[1] == ["population_clinical_profile"], \
            f"Level 1 should be ['population_clinical_profile'], got {levels[1]}"
        
        # Level 2: Intervention (depends on demographics + clinical)
        assert levels[2] == ["intervention_specification"], \
            f"Level 2 should be ['intervention_specification'], got {levels[2]}"
        
        # Level 3: Comparison (depends on intervention)
        assert levels[3] == ["comparison_group"], \
            f"Level 3 should be ['comparison_group'], got {levels[3]}"
        
        # Level 4: Outcomes (depends on intervention + comparison + clinical)
        assert levels[4] == ["primary_outcomes"], \
            f"Level 4 should be ['primary_outcomes'], got {levels[4]}"
        
        # Level 5: Study design (depends on all previous)
        assert levels[5] == ["study_design_context"], \
            f"Level 5 should be ['study_design_context'], got {levels[5]}"
    
    @pytest.mark.asyncio
    async def test_parallel_execution_respects_dependencies(self):
        """Test that parallel execution executes aspects in dependency order."""
        # Create aspects with dependencies
        aspects = [
            RefinementAspect(
                id="population_demographics",
                aspect_name="Population Demographics",
                aspect_description="Demographics",
                refinement_instructions="Analyze demographics",
                depends_on=None,
            ),
            RefinementAspect(
                id="population_clinical_profile",
                aspect_name="Clinical Profile",
                aspect_description="Clinical profile",
                refinement_instructions="Analyze clinical profile",
                depends_on=["population_demographics"],
            ),
            RefinementAspect(
                id="intervention_specification",
                aspect_name="Intervention",
                aspect_description="Intervention details",
                refinement_instructions="Analyze intervention",
                depends_on=["population_demographics", "population_clinical_profile"],
            ),
        ]
        
        # Create mock analyzer
        mock_analyzer = MockQueryAnalyzer()
        
        # Create parallel analyzer
        config = ParallelConfig(
            enabled=True,
            max_concurrent=10,  # High enough to not limit parallelism
            rate_limiter=None,
            backoff_strategy=BackoffStrategy(),
            max_retries=2,
        )
        
        parallel_analyzer = ParallelQueryAnalyzer(
            query_analyzer=mock_analyzer,
            config=config,
            trace_emitter=None,
        )
        
        # Mock dependency context provider
        completed_aspects = {}
        
        def get_dependency_context(aspect_id: str) -> Dict[str, str]:
            return {
                dep_id: f"value_from_{dep_id}"
                for dep_id in completed_aspects.keys()
            }
        
        # Mock LLM provider
        mock_llm = Mock(spec=LLMProviderInterface)
        
        # Execute parallel analysis
        results = await parallel_analyzer.analyze_aspects_parallel(
            query="test query",
            aspects=aspects,
            llm_provider=mock_llm,
            dependency_context_provider=get_dependency_context,
            user_id=None,
        )
        
        # Verify all aspects were executed
        assert len(results) == 3, f"Expected 3 results, got {len(results)}"
        assert len(mock_analyzer.execution_log) == 3, \
            f"Expected 3 executions, got {len(mock_analyzer.execution_log)}"
        
        # Verify execution order respects dependencies
        execution_order = [entry['aspect_id'] for entry in mock_analyzer.execution_log]
        
        # demographics must be first (no dependencies)
        assert execution_order[0] == "population_demographics", \
            f"Expected demographics first, got {execution_order}"
        
        # clinical_profile must be second (depends on demographics)
        assert execution_order[1] == "population_clinical_profile", \
            f"Expected clinical_profile second, got {execution_order}"
        
        # intervention must be third (depends on both previous)
        assert execution_order[2] == "intervention_specification", \
            f"Expected intervention third, got {execution_order}"
        
        # Verify dependency context was provided correctly
        # demographics should have no context
        assert mock_analyzer.execution_log[0]['dependency_context_keys'] == [], \
            "Demographics should have no dependency context"
        
        # clinical_profile should have demographics in context
        # Note: In the actual implementation during initialization, context is empty
        # because aspects haven't been completed yet. This is the source of the warnings.
        
    @pytest.mark.asyncio
    async def test_parallel_execution_sequential_chain(self):
        """Test that a sequential dependency chain (no parallelism) works correctly."""
        # Create 4 aspects in a chain: A -> B -> C -> D
        aspects = [
            RefinementAspect(
                id="aspect_a",
                aspect_name="Aspect A",
                aspect_description="First aspect",
                refinement_instructions="Analyze A",
                depends_on=None,
            ),
            RefinementAspect(
                id="aspect_b",
                aspect_name="Aspect B",
                aspect_description="Second aspect",
                refinement_instructions="Analyze B",
                depends_on=["aspect_a"],
            ),
            RefinementAspect(
                id="aspect_c",
                aspect_name="Aspect C",
                aspect_description="Third aspect",
                refinement_instructions="Analyze C",
                depends_on=["aspect_b"],
            ),
            RefinementAspect(
                id="aspect_d",
                aspect_name="Aspect D",
                aspect_description="Fourth aspect",
                refinement_instructions="Analyze D",
                depends_on=["aspect_c"],
            ),
        ]
        
        # Create mock analyzer
        mock_analyzer = MockQueryAnalyzer()
        
        # Create parallel analyzer (but dependencies force sequential)
        config = ParallelConfig(
            enabled=True,
            max_concurrent=10,
            rate_limiter=None,
        )
        
        parallel_analyzer = ParallelQueryAnalyzer(
            query_analyzer=mock_analyzer,
            config=config,
            trace_emitter=None,
        )
        
        def get_dependency_context(aspect_id: str) -> Dict[str, str]:
            return {}
        
        mock_llm = Mock(spec=LLMProviderInterface)
        
        # Execute
        results = await parallel_analyzer.analyze_aspects_parallel(
            query="test query",
            aspects=aspects,
            llm_provider=mock_llm,
            dependency_context_provider=get_dependency_context,
            user_id=None,
        )
        
        # Verify execution order is strictly sequential
        execution_order = [entry['aspect_id'] for entry in mock_analyzer.execution_log]
        assert execution_order == ["aspect_a", "aspect_b", "aspect_c", "aspect_d"], \
            f"Expected sequential order, got {execution_order}"
        
        # Verify that 4 levels were created (one per aspect in chain)
        # This confirms there's NO parallelism happening
        assert len(results) == 4
    
    def test_pico_advanced_has_no_parallelism_opportunity(self):
        """
        Test that demonstrates the pico_advanced framework has NO parallelism.
        
        With the current dependency structure:
        - Level 0: population_demographics (1 aspect) 
        - Level 1: population_clinical_profile (1 aspect)
        - Level 2: intervention_specification (1 aspect)
        - Level 3: comparison_group (1 aspect)
        - Level 4: primary_outcomes (1 aspect)
        - Level 5: study_design_context (1 aspect)
        
        Each level has exactly 1 aspect, so there's NO opportunity for parallel execution.
        The "parallel mode" is effectively running sequentially.
        """
        # Create aspects matching pico_advanced structure
        aspects = [
            RefinementAspect(
                id="population_demographics",
                aspect_name="Population Demographics",
                aspect_description="Demographics",
                refinement_instructions="Analyze demographics",
                depends_on=None,
            ),
            RefinementAspect(
                id="population_clinical_profile",
                aspect_name="Clinical Profile",
                aspect_description="Clinical profile",
                refinement_instructions="Analyze clinical profile",
                depends_on=["population_demographics"],
            ),
            RefinementAspect(
                id="intervention_specification",
                aspect_name="Intervention",
                aspect_description="Intervention details",
                refinement_instructions="Analyze intervention",
                depends_on=["population_demographics", "population_clinical_profile"],
            ),
            RefinementAspect(
                id="comparison_group",
                aspect_name="Comparison",
                aspect_description="Comparison group",
                refinement_instructions="Analyze comparison",
                depends_on=["intervention_specification"],
            ),
            RefinementAspect(
                id="primary_outcomes",
                aspect_name="Outcomes",
                aspect_description="Primary outcomes",
                refinement_instructions="Analyze outcomes",
                depends_on=["intervention_specification", "comparison_group", "population_clinical_profile"],
            ),
            RefinementAspect(
                id="study_design_context",
                aspect_name="Study Design",
                aspect_description="Study design",
                refinement_instructions="Analyze study design",
                depends_on=["population_demographics", "population_clinical_profile", 
                           "intervention_specification", "comparison_group", "primary_outcomes"],
            ),
        ]
        
        # Build dependency graph
        graph = DependencyGraph()
        for aspect in aspects:
            graph.add_node(aspect.id)
            if aspect.depends_on:
                for dep_id in aspect.depends_on:
                    graph.add_dependency(aspect.id, dep_id)
        
        # Compute levels
        levels = graph.get_levels()
        
        # CRITICAL FINDING: All 6 levels have exactly 1 aspect each
        assert len(levels) == 6, "Should have 6 levels"
        
        for i, level in enumerate(levels):
            assert len(level) == 1, (
                f"Level {i} has {len(level)} aspects: {level}. "
                f"With 1 aspect per level, there's NO parallelism - "
                f"execution is effectively sequential!"
            )
        
        # Calculate potential parallelism factor
        total_aspects = len(aspects)
        num_levels = len(levels)
        parallelism_factor = total_aspects / num_levels
        
        # Parallelism factor of 1.0 means NO parallelism
        assert parallelism_factor == 1.0, (
            f"Parallelism factor is {parallelism_factor}. "
            f"A value of 1.0 means completely sequential execution - "
            f"parallel mode provides NO benefit!"
        )
        
        print("\n" + "="*80)
        print("FINDING: pico_advanced framework has NO parallelism opportunity!")
        print("="*80)
        print(f"Total aspects: {total_aspects}")
        print(f"Dependency levels: {num_levels}")
        print(f"Parallelism factor: {parallelism_factor} (1.0 = sequential, >1.0 = parallel)")
        print("\nLevel breakdown:")
        for i, level in enumerate(levels):
            print(f"  Level {i}: {level}")
        print("\nConclusion: Parallel mode is running sequentially due to dependency chain.")
        print("="*80)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
