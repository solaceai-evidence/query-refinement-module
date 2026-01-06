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
            initial_query: initialQuery
        });
        return response.data;
    },

    // Continue refinement conversation
    async continueRefinement(sessionId, queryId, aspectId, userResponse) {
        const response = await apiClient.post('/api/refinement/continue', {
            session_id: sessionId,
            query_id: queryId,
            aspect_id: aspectId,
            user_response: userResponse
        });
        return response.data;
    },

    // Get synthesis (final result)
    async getSynthesis(sessionId, queryId) {
        const response = await apiClient.post('/api/refinement/synthesize', {
            session_id: sessionId,
            query_id: queryId
        });
        return response.data;
    },

    // Get query details
    async getQuery(queryId) {
        const response = await apiClient.get(`/api/queries/${queryId}`);
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
    async submitFeedback(queryId, rating, comment = null) {
        const response = await apiClient.post('/api/feedback', {
            query_id: queryId,
            rating,
            comment
        });
        return response.data;
    }
};
