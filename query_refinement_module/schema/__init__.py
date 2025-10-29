"""
Schema module for query refinement.

This module provides:
- RefinementAspect: Core data model for refinement aspects
- Dependency validation and topological sorting
- Framework registry for loading custom schemas from YAML

Usage:
    from schema import RefinementAspect, get_framework, list_frameworks
    
    # Get a custom framework
    pico = get_framework("pico_clinical")
    
    # List available frameworks
    frameworks = list_frameworks()
"""

from .model import RefinementAspect
from .dependencies import validate_dependencies, sort_aspects_by_dependencies
from .registry import (
    list_frameworks,
    get_framework,
    describe_framework,
)

__all__ = [
    # Core model
    "RefinementAspect",
    # Dependency utility
    "sort_aspects_by_dependencies",
    # Registry functions
    "list_frameworks",
    "get_framework",
    "describe_framework",
]
