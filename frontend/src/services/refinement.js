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
        const response = await apiClient.get('/refinement/frameworks');
        return response.data;
    },

    /**
     * Start a new refinement session
     * @param {string} frameworkName - Name of the refinement framework
     * @param {string} initialQuery - User's original query
     * @returns {Promise<StartRefinementResponse>}
     */
    async startRefinement(frameworkName, initialQuery) {
        const response = await apiClient.post('/refinement/start', {
            framework_name: frameworkName,
            original_query: initialQuery,
            source: 'gui'
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
        const url = `/refinement/queries/${queryId}/answer`;
        const isCommand = userResponse.startsWith('/');

        logger.info('Continue refinement', {
            queryId,
            isCommand,
            force,
            command: isCommand ? userResponse : undefined
        });

        try {
            const response = await apiClient.post(url, {
                answer: userResponse,
                force: force
            });

            logger.debug('Refinement response received', response.data);

            return response.data;
        } catch (error) {
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
            const response = await apiClient.post('/refinement/synthesize', {
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
        const response = await apiClient.get(`/queries/${queryId}`);
        return response.data;
    },

    /**
     * Get refinement status
     * @param {number} queryId - Query ID
     * @returns {Promise<GetRefinementStatusResponse>}
     */
    async getStatus(queryId) {
        const response = await apiClient.get(`/refinement/queries/${queryId}/status`, {
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
        const response = await apiClient.get('/queries', {
            params: { skip, limit }
        });
        return response.data;
    },

    /**
     * Submit feedback for a query
     *
     * Backend behavior:
     * - submitting feedback for a query marks the workflow as complete
     * - data consent is explicit via consent_to_use_data
     *
     * @param {number} queryId - Query ID
     * @param {number|null} rating - Rating (1-5)
     * @param {string|null} comments - Required free-text comments
     * @param {object|null} metadata - Optional structured survey responses
     * @param {boolean} consentToUseData - Explicit consent to retain/use data
     * @returns {Promise<any>}
     */
    async submitFeedback(queryId, rating, comments = null, metadata = null, consentToUseData = false) {
        const response = await apiClient.post('/feedback/', {
            query_id: queryId,
            rating,
            comments,
            additional_metadata: metadata,
            consent_to_use_data: consentToUseData,
        });
        return response.data;
    },

    /**
     * Get current user's workflow status
     * @returns {Promise<any>}
     */
    async getUserStatus() {
        const response = await apiClient.get('/auth/me/status');
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
            const response = await apiClient.post('/refinement/sessions/abandon', {
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
