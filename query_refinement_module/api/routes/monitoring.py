"""
Monitoring and observability endpoints.

Provides runtime metrics and health information for production monitoring.
"""
import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from query_refinement_module.api.dependencies import get_llm_provider
from query_refinement_module.providers import LiteLLMProvider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


@router.get("/circuit-breakers")
async def get_circuit_breaker_status(
    llm_provider: LiteLLMProvider = Depends(get_llm_provider)
) -> Dict[str, Any]:
    """
    Get circuit breaker status for all LLM providers.
    
    Returns real-time circuit breaker metrics including:
    - Current state (CLOSED, OPEN, HALF_OPEN)
    - Failure/success counts
    - Last failure/success timestamps
    - Total calls and rejected calls
    
    Use this endpoint to:
    - Monitor provider health in production
    - Debug LLM availability issues
    - Set up alerts for circuit breaker state changes
    - Track provider reliability over time
    
    Returns:
        Circuit breaker metrics for all providers
    """
    try:
        metrics = llm_provider.get_circuit_breaker_metrics()
        
        logger.info(
            "Circuit breaker status requested",
            extra={
                "enabled": metrics.get("circuit_breaker_enabled", False),
                "provider_count": len(metrics.get("providers", {}))
            }
        )
        
        return metrics
    except Exception as e:
        logger.error(
            "Failed to retrieve circuit breaker metrics",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve circuit breaker metrics"
        )


@router.get("/llm-health")
async def get_llm_health(
    llm_provider: LiteLLMProvider = Depends(get_llm_provider),
    test_connection: bool = False
) -> Dict[str, Any]:
    """
    Get LLM provider health summary.
    
    Combines circuit breaker status with provider configuration
    to give a comprehensive health overview.
    
    Query Parameters:
        test_connection: If true, makes a minimal test call to verify API key and credits
    
    Returns:
        LLM health status and configuration
    """
    try:
        cb_metrics = llm_provider.get_circuit_breaker_metrics()
        
        # Optionally test actual LLM connection
        connection_test_result = None
        if test_connection:
            try:
                # Make a minimal test call to verify API key and credits
                test_result = await llm_provider.complete_async(
                    user_prompt="Test",
                    system_prompt="Reply with OK",
                    max_tokens=5
                )
                connection_test_result = {
                    "success": True,
                    "message": "API key valid and credits available",
                    "response": test_result.context[:50] if test_result.context else None
                }
            except Exception as test_error:
                error_str = str(test_error).lower()
                
                # Check for specific error types
                if "credit" in error_str or "insufficient" in error_str or "quota" in error_str:
                    connection_test_result = {
                        "success": False,
                        "error_type": "insufficient_credits",
                        "message": "API credits exhausted or insufficient balance",
                        "details": str(test_error)
                    }
                elif "api key" in error_str or "authentication" in error_str or "unauthorized" in error_str:
                    connection_test_result = {
                        "success": False,
                        "error_type": "authentication_failed",
                        "message": "API key invalid or authentication failed",
                        "details": str(test_error)
                    }
                elif "rate limit" in error_str:
                    connection_test_result = {
                        "success": False,
                        "error_type": "rate_limited",
                        "message": "Rate limit exceeded (temporary)",
                        "details": str(test_error)
                    }
                else:
                    connection_test_result = {
                        "success": False,
                        "error_type": "connection_failed",
                        "message": "Failed to connect to LLM provider",
                        "details": str(test_error)
                    }
        
        # Determine overall health status
        if cb_metrics.get("circuit_breaker_enabled", False):
            providers = cb_metrics.get("providers", {})
            
            # Check if any circuits are open
            open_circuits = [
                name for name, metrics in providers.items()
                if metrics.get("state") == "open"
            ]
            
            half_open_circuits = [
                name for name, metrics in providers.items()
                if metrics.get("state") == "half_open"
            ]
            
            if open_circuits:
                overall_status = "degraded"
                message = f"Circuit breaker OPEN for: {', '.join(open_circuits)}"
            elif half_open_circuits:
                overall_status = "recovering"
                message = f"Circuit breaker testing recovery for: {', '.join(half_open_circuits)}"
            else:
                overall_status = "healthy"
                message = "All LLM providers operational"
        else:
            overall_status = "healthy"
            message = "Circuit breaker disabled - health monitoring limited"
        
        # Override status if connection test failed
        if connection_test_result and not connection_test_result["success"]:
            overall_status = "unhealthy"
            message = connection_test_result["message"]
        
        response = {
            "status": overall_status,
            "message": message,
            "circuit_breakers": cb_metrics,
            "timestamp": None  # Could add timestamp if needed
        }
        
        if connection_test_result:
            response["connection_test"] = connection_test_result
        
        return response
        
    except Exception as e:
        logger.error(
            "Failed to retrieve LLM health",
            exc_info=True
        )
        return {
            "status": "unknown",
            "message": f"Health check failed: {str(e)}",
            "circuit_breakers": {"circuit_breaker_enabled": False}
        }
