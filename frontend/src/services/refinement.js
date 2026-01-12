import apiClient from './api';

export const refinementService = {
    // Get available frameworks
    async getFrameworks() {
        const response = await apiClient.get('/api/refinement/frameworks');
        return response.data;
    },

    // Start refinement session
    async startRefinement(frameworkName, initialQuery) {
        const response = await apiClient.post('/api/refinement/start', {
            framework_name: frameworkName,
            original_query: initialQuery
        });
        return response.data;
    },

    // Continue refinement conversation
    async continueRefinement(sessionId, queryId, userResponse) {
        const response = await apiClient.post(`/api/refinement/queries/${queryId}/answer`, {
            answer: userResponse
        });
        return response.data;
    },

    // Get synthesis (final result)
    async getSynthesis(queryId) {
        const response = await apiClient.post('/api/refinement/synthesize', {
            query_id: queryId
        });
        return response.data;
    },

    // Get query details
    async getQuery(queryId) {
        const response = await apiClient.get(`/api/queries/${queryId}`);
        return response.data;
    },

    // Get refinement status
    async getStatus(queryId) {
        const response = await apiClient.get(`/api/refinement/queries/${queryId}/status`);
        return response.data;
    },

    // List user queries
    async listQueries(skip = 0, limit = 50) {
        const response = await apiClient.get('/api/queries', {
            params: { skip, limit }
        });
        return response.data;
    },

    // Submit feedback
    async submitFeedback(queryId, rating, comments = null) {
        const response = await apiClient.post('/api/feedback', {
            query_id: queryId,
            rating,
            comments
        });
        return response.data;
    }
};
