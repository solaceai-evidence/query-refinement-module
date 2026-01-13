import apiClient from './api';

/**
 * @typedef {import('../types/api').RefinementService} RefinementService
 * @typedef {import('../types/api').StartRefinementResponse} StartRefinementResponse
 * @typedef {import('../types/api').ContinueRefinementResponse} ContinueRefinementResponse
 * @typedef {import('../types/api').GetRefinementStatusResponse} GetRefinementStatusResponse
 * @typedef {import('../types/api').SynthesizeQueryResponse} SynthesizeQueryResponse
 */

/**
 * Service for interacting with the Query Refinement API
 * @type {RefinementService}
 */
export const refinementService = {
    /**
     * Get available frameworks
     * @returns {Promise<string[]>}
     */
    async getFrameworks() {
        const response = await apiClient.get('/api/refinement/frameworks');
        return response.data;
    },

    /**
     * Start a new refinement session
     * @param {string} frameworkName - Name of the refinement framework
     * @param {string} initialQuery - User's original query
     * @returns {Promise<StartRefinementResponse>}
     */
    async startRefinement(frameworkName, initialQuery) {
        const response = await apiClient.post('/api/refinement/start', {
            framework_name: frameworkName,
            original_query: initialQuery
        });
        return response.data;
    },

    /**
     * Continue refinement with user's answer or command
     * @param {number} sessionId - Session ID (for reference, not sent to backend)
     * @param {number} queryId - Query ID
     * @param {string} userResponse - User's answer or command (e.g., "/skip")
     * @param {boolean} [force=false] - Force execution even if it invalidates dependent aspects
     * @returns {Promise<ContinueRefinementResponse>}
     */
    async continueRefinement(sessionId, queryId, userResponse, force = false) {
        const url = `/api/refinement/queries/${queryId}/answer`;
        console.log('[API] continueRefinement called:', { sessionId, queryId, userResponse, force, url });
        try {
            const response = await apiClient.post(url, {
                answer: userResponse,
                force: force
            });
            console.log('[API] continueRefinement response:', response.data);
            return response.data;
        } catch (error) {
            console.error('[API] continueRefinement error:', {
                message: error.message,
                response: error.response?.data,
                status: error.response?.status,
                url
            });
            throw error;
        }
    },

    /**
     * Get synthesis (final refined query)
     * @param {number} queryId - Query ID
     * @returns {Promise<SynthesizeQueryResponse>}
     */
    async getSynthesis(queryId) {
        const response = await apiClient.post('/api/refinement/synthesize', {
            query_id: queryId
        });
        return response.data;
    },

    /**
     * Get query details
     * @param {number} queryId - Query ID
     * @returns {Promise<any>}
     */
    async getQuery(queryId) {
        const response = await apiClient.get(`/api/queries/${queryId}`);
        return response.data;
    },

    /**
     * Get refinement status
     * @param {number} queryId - Query ID
     * @returns {Promise<GetRefinementStatusResponse>}
     */
    async getStatus(queryId) {
        const response = await apiClient.get(`/api/refinement/queries/${queryId}/status`);
        return response.data;
    },

    /**
     * List user's queries
     * @param {number} [skip=0] - Number of records to skip
     * @param {number} [limit=50] - Maximum number of records to return
     * @returns {Promise<any[]>}
     */
    async listQueries(skip = 0, limit = 50) {
        const response = await apiClient.get('/api/queries', {
            params: { skip, limit }
        });
        return response.data;
    },

    /**
     * Submit feedback for a query
     * @param {number} queryId - Query ID
     * @param {number} rating - Rating (1-5)
     * @param {string | null} [comments=null] - Optional comments
     * @returns {Promise<any>}
     */
    async submitFeedback(queryId, rating, comments = null) {
        const response = await apiClient.post('/api/feedback', {
            query_id: queryId,
            rating,
            comments
        });
        return response.data;
    }
};
