"""
API versioning middleware for handling deprecated versions and version validation.

Adds deprecation warnings to responses for deprecated API versions.
"""
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from query_refinement_module.api.versioning import is_deprecated, validate_version

logger = logging.getLogger(__name__)


class APIVersionMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle API versioning concerns.
    
    Features:
    - Adds deprecation warnings to responses
    - Validates version in request path
    - Logs version usage for analytics
    """
    
    async def dispatch(self, request: Request, call_next):
        """
        Process request and add version-related headers.
        
        Args:
            request: Incoming request
            call_next: Next middleware in chain
        
        Returns:
            Response with version headers added
        """
        # Extract version from path (e.g., /api/v1/refinement -> v1)
        path_parts = request.url.path.split('/')
        version = None
        
        if len(path_parts) >= 3 and path_parts[1] == 'api' and path_parts[2].startswith('v'):
            version = path_parts[2]
        
        # Validate version if present
        if version and not validate_version(version):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=400,
                content={
                    "error": "invalid_api_version",
                    "message": f"API version '{version}' is not supported",
                    "supported_versions": ["v1"],
                    "help": "Use /api/v1/... for the current stable API"
                }
            )
        
        # Process request
        response = await call_next(request)
        
        # Add version headers
        if version:
            response.headers["X-API-Version"] = version
            
            # Add deprecation warning if applicable
            if is_deprecated(version):
                response.headers["Warning"] = (
                    f'299 - "API version {version} is deprecated and will be removed. '
                    f'Please upgrade to the latest version."'
                )
                logger.warning(
                    f"Deprecated API version {version} used",
                    extra={
                        "path": request.url.path,
                        "version": version,
                        "client": request.client.host if request.client else "unknown"
                    }
                )
        
        return response
