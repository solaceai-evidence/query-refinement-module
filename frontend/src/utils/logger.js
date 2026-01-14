/**
 * Production-ready logging utility
 * - debug: Development only (verbose traces)
 * - info: Always logged (important operational events)
 * - warn: Always logged (warnings and issues)
 * - error: Always logged (errors with context)
 */

const isDevelopment = import.meta.env.MODE === 'development';

export const logger = {
    /**
     * Debug logs - only in development (verbose traces)
     * Use for: detailed state tracking, variable inspection
     */
    debug: (...args) => {
        if (isDevelopment) {
            console.log('[DEBUG]', ...args);
        }
    },

    /**
     * Info logs - ALWAYS logged (production observability)
     * Use for: API calls, user actions, state transitions
     */
    info: (message, context = {}) => {
        console.log('[INFO]', message, context);
    },

    /**
     * Warning logs - ALWAYS logged (production monitoring)
     * Use for: recoverable errors, validation issues, deprecations
     */
    warn: (message, context = {}) => {
        console.warn('[WARN]', message, context);
    },

    /**
     * Error logs - ALWAYS logged (production error tracking)
     * Use for: exceptions, failures, critical issues
     */
    error: (message, error = null, context = {}) => {
        if (error) {
            console.error('[ERROR]', message, {
                ...context,
                error: error.message || error,
                stack: error.stack,
                response: error.response?.data
            });
        } else {
            console.error('[ERROR]', message, context);
        }
    }
};
