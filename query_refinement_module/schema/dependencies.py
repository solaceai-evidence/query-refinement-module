"""
Dependency validation and topological sorting for refinement aspects.

This module provides utilities for validating and ordering refinement aspects
based on their dependencies using Python's built-in graphlib.
"""

from typing import List
from graphlib import TopologicalSorter, CycleError
from .model import RefinementAspect

__all__ = ["sort_aspects_by_dependencies"]


def validate_dependencies(refinement_framework: List[RefinementAspect]) -> None:
    """
    Validate refinement aspect dependencies for a refinement framework.
    
    Checks for non-existent refinement aspect references.
    Note: Circular dependencies are detected during sorting.
    
    Args:
        refinement_framework: List of RefinementAspect objects to validate

    Raises:
        ValueError: If dependencies reference non-existent aspects
    """
    dimension_ids = {dim.id for dim in refinement_framework}

    # Check for non-existent dependencies
    for dim in refinement_framework:
        for dep_id in dim.depends_on:
            if dep_id not in dimension_ids:
                raise ValueError(
                    f"Refinement aspect '{dim.id}' depends on non-existent refinement aspect '{dep_id}'. "
                    f"Available refinement aspects: {', '.join(sorted(dimension_ids))}"
                )


def sort_aspects_by_dependencies(refinement_framework: List[RefinementAspect]) -> List[RefinementAspect]:
    """
    Sort refinement aspects by their dependencies using topological sort.
    
    Refinement aspects with no dependencies come first, followed by those that depend on them, etc.
    Uses Python's built-in graphlib.TopologicalSorter for efficient, reliable sorting.
    
    Args:
        refinement_framework: List of RefinementAspect objects to sort

    Returns:
        Sorted list of refinement aspects (dependencies satisfied in order)
        
    Raises:
        ValueError: If circular dependencies exist or invalid dependencies are found
    """
    # Validate non-existent dependencies first
    validate_dependencies(refinement_framework)
    
    # Build dependency graph and perform topological sort
    graph = {dim.id: dim.depends_on for dim in refinement_framework}
    
    try:
        ts = TopologicalSorter(graph)
        sorted_ids = list(ts.static_order())
    except CycleError as e:
        raise ValueError(f"Circular dependency detected in schema: {e}") from e
    
    # Map back to RefinementAspect objects
    dim_map = {dim.id: dim for dim in refinement_framework}
    return [dim_map[dim_id] for dim_id in sorted_ids]
