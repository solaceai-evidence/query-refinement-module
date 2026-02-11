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

router = APIRouter(tags=["Monitoring"])


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
    llm_provider: LiteLLMProvider = Depends(get_llm_provider)
) -> Dict[str, Any]:
    """
    Get LLM provider health summary.
    
    Combines circuit breaker status with provider configuration
    to give a comprehensive health overview.
    
    Returns:
        LLM health status and configuration
    """
    try:
        cb_metrics = llm_provider.get_circuit_breaker_metrics()
        
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
        
        return {
            "status": overall_status,
            "message": message,
            "circuit_breakers": cb_metrics,
            "timestamp": None  # Could add timestamp if needed
        }
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
