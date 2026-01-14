/**
 * Type guard utilities for runtime type checking
 * @module types
 */

/**
 * Check if a response is a CommandResponse
 * @param {import('./api').ContinueRefinementResponse} response
 * @returns {response is import('./api').CommandResponse}
 */
export function isCommandResponse(response) {
    return 'command_type' in response;
}

/**
 * Check if a response is a SubmitAnswerResponse
 * @param {import('./api').ContinueRefinementResponse} response
 * @returns {response is import('./api').SubmitAnswerResponse}
 */
export function isSubmitAnswerResponse(response) {
    return 'refinement_step_id' in response && 'followup_id' in response;
}

/**
 * Validate NextPrompt has required fields
 * @param {any} obj
 * @returns {obj is import('./api').NextPrompt}
 */
export function isNextPrompt(obj) {
    return obj
        && typeof obj.aspect_id === 'string'
        && typeof obj.aspect_name === 'string'
        && typeof obj.question === 'string';
}

/**
 * Create a typed conversation history item
 * @param {'query' | 'question' | 'answer' | 'command'} type
 * @param {string} content
 * @param {Object} options
 * @returns {import('./api').ConversationHistoryItem}
 */
export function createHistoryItem(type, content, options = {}) {
    return {
        type,
        content,
        timestamp: new Date().toISOString(),
        ...options
    };
}
