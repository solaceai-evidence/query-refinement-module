"""
Refinement framework registry for loading and managing custom refinement frameworks from YAML.

This module handles:
- Loading frameworks from REFINEMENT_FRAMEWORK_PATH environment variable
- Validating and sorting refinement aspects by dependencies
- Providing access to registered frameworks
"""

import os
from pathlib import Path
from typing import List, Dict, Any
import logging

from .model import RefinementAspect
from .dependencies import sort_aspects_by_dependencies

logger = logging.getLogger(__name__)

__all__ = [
    "list_frameworks",
    "get_framework",
    "describe_framework",
]


def _load_refinement_framework() -> Dict[str, List[RefinementAspect]]:
    """
    Load refinement framework from external YAML file specified by REFINEMENT_FRAMEWORK_PATH.
    
    The REFINEMENT_FRAMEWORK_PATH environment variable must point to a YAML file containing
    framework definitions.
    
    Returns:
        Dictionary mapping framework names to lists of RefinementAspect objects
    """
    refinement_frameworks: Dict[str, List[RefinementAspect]] = {}
    
    # Check if PyYAML is available
    try:
        import yaml
    except ImportError:
        logger.error(
            "PyYAML not installed. refinement framework require PyYAML. "
            "Install with: pip install pyyaml"
        )
        return refinement_frameworks
    
    # Get path from environment variable
    env_path = os.getenv("REFINEMENT_FRAMEWORK_PATH")
    if not env_path:
        logger.error(
            "REFINEMENT_FRAMEWORK_PATH environment variable not set. "
            "Please set it to the path of your refinement framework YAML file."
        )
        return refinement_frameworks
    
    framework_path = Path(env_path)
    
    # Check if file exists
    if not framework_path.exists():
        logger.error(f"refinement framework file not found: {framework_path}")
        return refinement_frameworks
    
    if not framework_path.is_file():
        logger.error(f"REFINEMENT_FRAMEWORK_PATH must point to a file, not a directory: {framework_path}")
        return refinement_frameworks
    
    # Load and parse YAML file
    try:
        logger.info(f"Loading refinement framework from: {framework_path}")
        with open(framework_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        if not isinstance(data, dict):
            logger.error(f"Invalid YAML format in {framework_path}: expected dictionary at root level")
            return refinement_frameworks
        
        # Validate and convert to RefinementAspect objects
        for framework_name, dimensions_data in data.items():
            if not isinstance(dimensions_data, list):
                logger.warning(f"Skipping framework '{framework_name}': expected list of dimensions")
                continue
            
            refinement_aspects = []
            for dim_data in dimensions_data:
                try:
                    dimension = RefinementAspect.from_dict(dim_data)
                    refinement_aspects.append(dimension)
                except (TypeError, ValueError) as e:
                    logger.warning(f"Skipping invalid dimension in framework '{framework_name}': {e}")
                    continue
            
            if refinement_aspects:
                # Validate dependencies
                try:
                    # Sort by dependencies
                    refinement_aspects = sort_aspects_by_dependencies(refinement_aspects)
                    refinement_frameworks[framework_name] = refinement_aspects
                    logger.info(f"Loaded framework '{framework_name}' with {len(refinement_aspects)} dimensions (validated and sorted)")
                except ValueError as e:
                    logger.error(f"Invalid dependencies in framework '{framework_name}': {e}")
                    continue
        
        if not refinement_frameworks:
            logger.warning(f"No valid frameworks found in {framework_path}")
            
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML from {framework_path}: {e}")
    except Exception as e:
        logger.error(f"Error loading refinement framework from {framework_path}: {e}")
    
    return refinement_frameworks


# ===============
# framework Registry
# ===============

# Load refinement framework from REFINEMENT_FRAMEWORK_PATH
REFINEMENT_FRAMEWORK_STORE: Dict[str, List[RefinementAspect]] = _load_refinement_framework()


def list_frameworks() -> List[str]:
    """
    List all available custom framework names loaded from REFINEMENT_FRAMEWORK_PATH.

    Returns:
        List of framework names
    """
    return list(REFINEMENT_FRAMEWORK_STORE.keys())


def get_framework(framework_name: str) -> List[RefinementAspect]:
    """
    Retrieve a custom framework by name.

    Args:
        framework_name: Name of the framework as defined in your custom_frameworks.yaml file

    Returns:
        List of RefinementAspect objects for the framework

    Raises:
        ValueError: If framework_name is not found in the loaded frameworks
    """
    if framework_name not in REFINEMENT_FRAMEWORK_STORE:
        available = ", ".join(REFINEMENT_FRAMEWORK_STORE.keys()) if REFINEMENT_FRAMEWORK_STORE else "none"
        raise ValueError(
            f"Unknown framework '{framework_name}'. Available frameworks: {available}. "
            f"Make sure REFINEMENT_FRAMEWORK_PATH is set and points to a valid YAML file."
        )
    return REFINEMENT_FRAMEWORK_STORE[framework_name]


def describe_framework(refinement_framework_name: str) -> Dict[str, Any]:
    """
    Get detailed description of a refinement framework including all dimensions.

    Args:
        refinement_framework_name: Name of the refinement framework

    Returns:
        Dictionary with refinement framework metadata and dimension details
    """
    refinement_framework = get_framework(refinement_framework_name)

    return {
        "name": refinement_framework_name,
        "num_dimensions": len(refinement_framework),
        "dimensions": [
            {
                "id": dim.id,
                "name": dim.name,
                "description": dim.description
            }
            for dim in refinement_framework
        ],
    }
