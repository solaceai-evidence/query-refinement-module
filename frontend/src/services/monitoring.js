import apiClient from './api';
import { logger } from '../utils/logger';

function normalizeProviderHealth(providers = {}) {
    return Object.fromEntries(
        Object.entries(providers).map(([name, provider]) => {
            const state = provider?.state?.toLowerCase?.();
            return [
                name,
                {
                    ...provider,
                    is_healthy: provider?.is_healthy ?? (state !== 'open' && state !== 'half_open')
                }
            ];
        })
    );
}

function normalizeLLMHealthResponse(data = {}) {
    const providers = normalizeProviderHealth(
        data.providers ?? data.circuit_breakers?.providers ?? {}
    );

    return {
        ...data,
        overall_health: data.overall_health ?? data.status ?? 'unknown',
        providers
    };
}

/**
 * Service for monitoring LLM health and circuit breaker status
 */
export const monitoringService = {
    /**
     * Get circuit breaker status for all LLM providers
     * @returns {Promise<object>}
     */
    async getCircuitBreakerStatus() {
        try {
            const response = await apiClient.get('/monitoring/circuit-breakers');
            return response.data;
        } catch (err) {
            logger.error('Failed to fetch circuit breaker status', {
                error: err.message,
                status: err.response?.status
            });
            throw err;
        }
    },

    /**
     * Get overall LLM health summary
     * @returns {Promise<object>}
     */
    async getLLMHealth() {
        try {
            const response = await apiClient.get('/monitoring/llm-health');
            return normalizeLLMHealthResponse(response.data);
        } catch (err) {
            logger.error('Failed to fetch LLM health', {
                error: err.message,
                status: err.response?.status
            });
            throw err;
        }
    },

    /**
     * Check if a specific provider is healthy
     * @param {string} providerName - Provider name (e.g., 'openai', 'anthropic')
     * @returns {Promise<boolean>}
     */
    async isProviderHealthy(providerName) {
        try {
            const health = await this.getLLMHealth();
            const provider = health.providers?.[providerName];
            return provider?.is_healthy === true;
        } catch {
            // If monitoring fails, assume healthy to avoid blocking
            return true;
        }
    }
};
