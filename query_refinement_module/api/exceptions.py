"""
Custom exceptions for the Query Refinement API.
"""
from fastapi import status


class QueryRefinementException(Exception):
    """Base exception for query refinement errors."""
    def __init__(self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class FrameworkNotFoundError(QueryRefinementException):
    """Raised when a refinement framework is not found."""
    def __init__(self, framework_name: str):
        message = f"Refinement framework '{framework_name}' not found"
        super().__init__(message, status_code=status.HTTP_404_NOT_FOUND)
        self.framework_name = framework_name


class LLMServiceError(QueryRefinementException):
    """Raised when the LLM service encounters an error."""
    def __init__(self, message: str, original_error: Exception = None):
        super().__init__(
            f"LLM service error: {message}",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )
        self.original_error = original_error


class LLMTimeoutError(QueryRefinementException):
    """Raised when the LLM service times out."""
    def __init__(self, message: str = "LLM service request timed out"):
        super().__init__(message, status_code=status.HTTP_504_GATEWAY_TIMEOUT)


class LLMRateLimitError(QueryRefinementException):
    """Raised when the LLM service rate limit is exceeded."""
    def __init__(self, message: str = "LLM service rate limit exceeded", retry_after: int = None):
        super().__init__(message, status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        self.retry_after = retry_after


class InvalidAPIKeyError(QueryRefinementException):
    """Raised when LLM API key is invalid or missing."""
    def __init__(self, message: str = "Invalid or missing LLM API key"):
        super().__init__(message, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ValidationError(QueryRefinementException):
    """Raised when request validation fails."""
    def __init__(self, message: str, field: str = None):
        super().__init__(message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.field = field


class ResourceNotFoundError(QueryRefinementException):
    """Raised when a requested resource is not found."""
    def __init__(self, resource_type: str, resource_id: int):
        message = f"{resource_type} with ID {resource_id} not found"
        super().__init__(message, status_code=status.HTTP_404_NOT_FOUND)
        self.resource_type = resource_type
        self.resource_id = resource_id


class UnauthorizedError(QueryRefinementException):
    """Raised when user is not authorized to access a resource."""
    def __init__(self, message: str = "Unauthorized access to resource"):
        super().__init__(message, status_code=status.HTTP_403_FORBIDDEN)


class QueryAlreadyCompleteError(QueryRefinementException):
    """Raised when attempting to refine an already completed query."""
    def __init__(self, query_id: int):
        message = f"Query {query_id} is already complete"
        super().__init__(message, status_code=status.HTTP_400_BAD_REQUEST)
        self.query_id = query_id
