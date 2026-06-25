"""
Refinement framework registry for loading and managing frameworks from YAML.

This module handles:
- Loading frameworks from REFINEMENT_FRAMEWORK_PATH environment variable
- Validating and sorting dimensions by dependencies
- Providing access to registered frameworks
"""

import os
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
import yaml
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Use Pydantic model (with backward compat alias)
from .models import RefinementDimension, RefinementAspect
from .dependencies import sort_aspects_by_dependencies

logger = logging.getLogger(__name__)

__all__ = [
    "list_frameworks",
    "get_framework",
    "describe_framework",
    "reload_from_env",
    "get_last_load_error",
    "FrameworkLoadError",
]


class FrameworkLoadError(RuntimeError):
    """Raised when frameworks cannot be loaded from environment path."""
    pass


# Module-level cache for loaded frameworks
_FRAMEWORKS: Dict[str, List[RefinementAspect]] = {}
_LAST_LOAD_ERROR: Optional[str] = None
_FRAMEWORKS_LOCK = threading.RLock()


def _load_frameworks(*, raise_on_error: bool = False) -> Dict[str, List[RefinementAspect]]:
    """
    Load frameworks from YAML file specified by REFINEMENT_FRAMEWORK_PATH.

    Returns:
        Dict mapping framework names to lists of RefinementAspect objects

    Raises:
        FrameworkLoadError: If raise_on_error=True and loading fails
    """
    global _LAST_LOAD_ERROR
    
    framework_path = os.getenv("REFINEMENT_FRAMEWORK_PATH")
    if not framework_path:
        error_msg = "REFINEMENT_FRAMEWORK_PATH environment variable not set"
        _LAST_LOAD_ERROR = error_msg
        if raise_on_error:
            raise FrameworkLoadError(error_msg)
        logger.warning(error_msg)
        return {}
    
    yaml_path = Path(framework_path)
    if not yaml_path.exists():
        error_msg = f"Framework file not found: {yaml_path}"
        _LAST_LOAD_ERROR = error_msg
        if raise_on_error:
            raise FrameworkLoadError(error_msg)
        logger.error(error_msg)
        return {}
    
    try:
        document = yaml.safe_load(yaml_path.read_text())
        if not document or not isinstance(document, dict):
            error_msg = f"Invalid YAML structure in {yaml_path}"
            _LAST_LOAD_ERROR = error_msg
            if raise_on_error:
                raise FrameworkLoadError(error_msg)
            logger.error(error_msg)
            return {}
        
        frameworks = {}
        for framework_name, items in document.items():
            if not isinstance(items, list) or len(items) == 0:
                logger.warning(f"Framework '{framework_name}' has no items, skipping")
                continue

            # Load aspects
            aspects = []
            for item in items:
                if not isinstance(item, dict):
                    logger.warning(f"Skipping non-dict item in framework '{framework_name}'")
                    continue

                try:
                    aspect = RefinementAspect(**item)
                    aspects.append(aspect)
                except Exception as e:
                    logger.error(f"Failed to load aspect '{item.get('id', 'unknown')}' in framework '{framework_name}': {e}")
                    continue
            
            if aspects:
                # Sort by dependencies — also detects circular references
                try:
                    aspects = sort_aspects_by_dependencies(aspects)
                except ValueError as e:
                    error_msg = f"Invalid dependency graph in framework '{framework_name}': {e}"
                    logger.error(error_msg)
                    if raise_on_error:
                        raise FrameworkLoadError(error_msg) from e
                    # Skip the broken framework rather than loading it in an
                    # undefined order that could produce incorrect refinements.
                    _LAST_LOAD_ERROR = error_msg
                    continue
                
                frameworks[framework_name] = aspects
                logger.info(f"Loaded framework '{framework_name}' with {len(aspects)} aspects")
            else:
                logger.warning(f"Framework '{framework_name}' has no valid aspects")
        
        _LAST_LOAD_ERROR = None
        return frameworks
        
    except yaml.YAMLError as e:
        error_msg = f"YAML parsing error in {yaml_path}: {e}"
        _LAST_LOAD_ERROR = error_msg
        if raise_on_error:
            raise FrameworkLoadError(error_msg)
        logger.error(error_msg)
        return {}
    except Exception as e:
        error_msg = f"Unexpected error loading frameworks from {yaml_path}: {e}"
        _LAST_LOAD_ERROR = error_msg
        if raise_on_error:
            raise FrameworkLoadError(error_msg)
        logger.error(error_msg)
        return {}


def reload_from_env(*, raise_on_error: bool = False) -> Dict[str, List[RefinementAspect]]:
    """
    Reload frameworks from environment path, updating the module cache.
    
    Args:
        raise_on_error: If True, raise FrameworkLoadError on failures
    
    Returns:
        Dict mapping framework names to lists of RefinementAspect objects
    """
    global _FRAMEWORKS
    new = _load_frameworks(raise_on_error=raise_on_error)
    with _FRAMEWORKS_LOCK:
        _FRAMEWORKS = new
    return _FRAMEWORKS


def list_frameworks() -> List[str]:
    """
    List available framework names.
    
    Returns:
        List of framework names
    """
    if not _FRAMEWORKS:
        reload_from_env()
    with _FRAMEWORKS_LOCK:
        return list(_FRAMEWORKS.keys())


def get_framework(name: str) -> List[RefinementAspect]:
    """
    Get framework by name.
    
    Args:
        name: Framework name
        
    Returns:
        List of RefinementAspect objects for the framework
        
    Raises:
        KeyError: If framework not found
    """
    with _FRAMEWORKS_LOCK:
        if not _FRAMEWORKS:
            reload_from_env()
        if name not in _FRAMEWORKS:
            available = ", ".join(_FRAMEWORKS.keys()) if _FRAMEWORKS else "none"
            raise KeyError(f"Framework '{name}' not found. Available: {available}")
        return _FRAMEWORKS[name]


def describe_framework(name: str) -> Dict[str, Any]:
    """
    Get metadata about a framework.
    
    Args:
        name: Framework name
        
    Returns:
        Dict with framework metadata (aspect count, IDs, etc.)
    """
    aspects = get_framework(name)
    
    return {
        "name": name,
        "aspect_count": len(aspects),
        "aspect_ids": [a.id for a in aspects],
        "aspect_names": [a.name for a in aspects],
        "has_dependencies": any(a.depends_on for a in aspects),
    }


def get_last_load_error() -> Optional[str]:
    """
    Get the last error message from framework loading.
    
    Returns:
        Error message string or None if no error
    """
    return _LAST_LOAD_ERROR


# Initialize frameworks on import
reload_from_env()