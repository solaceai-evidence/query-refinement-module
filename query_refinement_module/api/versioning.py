"""
API versioning utilities and configuration.

This module provides utilities for API versioning using URL path-based versioning.
Example: /api/v1/refinement/start

Versioning Strategy:
- Version format: v{major} (e.g., v1, v2, v3)
- Location: URL path (/api/v1/...)
- Breaking changes: Increment major version
- Backward compatibility: Old versions remain available

Version History:
- v1: Initial API release (current)
"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class APIVersion(str, Enum):
    """Supported API versions."""
    V1 = "v1"
    # V2 = "v2"  # Future versions


# Current stable version
CURRENT_VERSION = APIVersion.V1

# Latest version (may include beta features)
LATEST_VERSION = APIVersion.V1

# Deprecated versions (still available but will be removed)
DEPRECATED_VERSIONS = []

# Minimum supported version
MIN_SUPPORTED_VERSION = APIVersion.V1


class VersionInfo(BaseModel):
    """API version information."""
    current_version: str
    latest_version: str
    supported_versions: list[str]
    deprecated_versions: list[str]
    min_supported_version: str


def get_version_info() -> VersionInfo:
    """
    Get comprehensive API version information.
    
    Returns:
        VersionInfo with all version details
    """
    supported = [v.value for v in APIVersion]
    
    return VersionInfo(
        current_version=CURRENT_VERSION.value,
        latest_version=LATEST_VERSION.value,
        supported_versions=supported,
        deprecated_versions=DEPRECATED_VERSIONS,
        min_supported_version=MIN_SUPPORTED_VERSION.value
    )


def get_api_prefix(version: Optional[APIVersion] = None) -> str:
    """
    Get the API prefix for a given version.
    
    Args:
        version: API version (defaults to CURRENT_VERSION)
    
    Returns:
        API prefix string (e.g., "/api/v1")
    
    Examples:
        >>> get_api_prefix(APIVersion.V1)
        '/api/v1'
        >>> get_api_prefix()
        '/api/v1'
    """
    if version is None:
        version = CURRENT_VERSION
    
    return f"/api/{version.value}"


def validate_version(version: str) -> bool:
    """
    Validate if a version string is supported.
    
    Args:
        version: Version string (e.g., "v1", "v2")
    
    Returns:
        True if version is supported, False otherwise
    """
    try:
        APIVersion(version)
        return True
    except ValueError:
        return False


def is_deprecated(version: str) -> bool:
    """
    Check if a version is deprecated.
    
    Args:
        version: Version string (e.g., "v1")
    
    Returns:
        True if version is deprecated
    """
    return version in DEPRECATED_VERSIONS
