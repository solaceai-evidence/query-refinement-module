import apiClient from './api';
import { logger } from '../utils/logger';

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
        const isCommand = userResponse.startsWith('/');

        console.log('[SERVICE v2.0] === STARTING continueRefinement ===');
        console.log('[SERVICE v2.0] URL:', url);
        console.log('[SERVICE v2.0] userResponse:', userResponse);
        console.log('[SERVICE v2.0] isCommand:', isCommand);

        logger.info('Continue refinement', {
            queryId,
            isCommand,
            force,
            command: isCommand ? userResponse : undefined
        });

        try {
            console.log('[SERVICE v2.0] About to make axios call...');

            const response = await apiClient.post(url, {
                answer: userResponse,
                force: force
            });

            console.log('[SERVICE v2.0] AXIOS CALL COMPLETED!');
            console.log('[SERVICE v2.0] Response status:', response.status);
            console.log('[SERVICE v2.0] Response data:', response.data);
            console.log('[SERVICE v2.0] Response data stringified:', JSON.stringify(response.data, null, 2));

            logger.debug('Refinement response received', response.data);

            console.log('[SERVICE v2.0] Returning response.data...');
            return response.data;
        } catch (error) {
            console.error('[SERVICE v2.0] === CAUGHT ERROR ===');
            console.error('[SERVICE v2.0] Error type:', error.constructor.name);
            console.error('[SERVICE v2.0] Error message:', error.message);
            console.error('[SERVICE v2.0] Error response:', error.response);
            console.error('[SERVICE v2.0] Error response data:', error.response?.data);
            console.error('[SERVICE v2.0] Full error:', error);

            logger.error('Continue refinement failed', error, {
                queryId,
                userResponse: isCommand ? userResponse : '[user answer]',
                force
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
        logger.info('Getting synthesis', { queryId });

        try {
            const response = await apiClient.post('/api/refinement/synthesize', {
                query_id: queryId
            });

            logger.info('Synthesis response received', {
                queryId,
                hasData: !!response.data,
                dataKeys: response.data ? Object.keys(response.data) : null,
                integratedStatementLength: response.data?.integrated_statement?.length || 0
            });

            // Validate response structure
            if (!response.data) {
                logger.error('Empty synthesis response', { queryId });
                throw new Error('Synthesis returned empty response');
            }

            if (!response.data.integrated_statement) {
                logger.error('Missing integrated_statement in synthesis response', {
                    queryId,
                    responseKeys: Object.keys(response.data)
                });
                throw new Error('Synthesis response missing integrated_statement field');
            }

            logger.info('Synthesis validated successfully', {
                queryId,
                integratedStatementPreview: response.data.integrated_statement.substring(0, 100)
            });

            return response.data;
        } catch (error) {
            logger.error('Get synthesis failed', error, { queryId });
            throw error;
        }
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
        const response = await apiClient.get(`/api/refinement/queries/${queryId}/status`, {
            timeout: 10000 // 10 second timeout for status checks (should be fast)
        });
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
    },

    /**
     * Get current user's workflow status
     * @returns {Promise<any>}
     */
    async getUserStatus() {
        const response = await apiClient.get('/api/auth/me/status');
        return response.data;
    },

    /**
     * Abandon a session and delete all its data
     * Used when user clicks "Start Over" to ensure session doesn't count toward limits
     * @param {number} sessionId - Session ID to abandon
     * @returns {Promise<any>}
     */
    async abandonSession(sessionId) {
        logger.info('Abandoning session', { sessionId });

        try {
            const response = await apiClient.post('/api/refinement/sessions/abandon', {
                session_id: sessionId
            });

            logger.info('Session abandoned successfully', {
                sessionId,
                deletionCounts: response.data?.deletion_counts
            });

            return response.data;
        } catch (error) {
            logger.error('Abandon session failed', error, { sessionId });
            throw error;
        }
    }
};
