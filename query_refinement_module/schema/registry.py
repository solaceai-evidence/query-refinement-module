"""
Refinement framework registry for loading and managing frameworks from YAML.

This module handles:
- Loading frameworks from REFINEMENT_FRAMEWORK_PATH environment variable
- Validating and sorting dimensions by dependencies
- Providing access to registered frameworks
"""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from .models import RefinementDimension
from .loaders import load_dimension_from_yaml
from .dependencies import sort_dimensions_by_dependencies

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


_LAST_LOAD_ERROR: Optional[str] = None


def _load_frameworks(*, raise_on_error: bool = False) -> Dict[str, List[RefinementDimension]]:
    """
    Load frameworks from YAML file specified by REFINEMENT_FRAMEWORK_PATH.
    
    The YAML structure should be:
```yaml