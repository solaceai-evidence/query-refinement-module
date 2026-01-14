/**
 * Production-ready logging utility with distributed tracing support
 * - debug: Development only (verbose traces)
 * - info: Always logged (important operational events)
 * - warn: Always logged (warnings and issues)
 * - error: Always logged (errors with context)
 * - setRequestContext: Store request_id and trace_id for correlation
 */

const isDevelopment = import.meta.env.MODE === 'development';

// Request context storage for distributed tracing
let currentRequestId = null;
let currentTraceId = null;

export const logger = {
    /**
     * Set request context for distributed tracing
     * Called by API interceptor when receiving X-Request-ID header
     */
    setRequestContext: (requestId, traceId = null) => {
        currentRequestId = requestId;
        currentTraceId = traceId;
    },

    /**
     * Clear request context after operation completes
     */
    clearRequestContext: () => {
        currentRequestId = null;
        currentTraceId = null;
    },

    /**
     * Get current request context for manual inclusion in logs
     */
    getRequestContext: () => ({
        request_id: currentRequestId,
        trace_id: currentTraceId
    }),

    /**
     * Add request context to log context object
     */
    _enrichContext: (context = {}) => {
        const enriched = { ...context };
        if (currentRequestId) {
            enriched.request_id = currentRequestId;
        }
        if (currentTraceId) {
            enriched.trace_id = currentTraceId;
        }
        return enriched;
    },

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
        console.log('[INFO]', message, logger._enrichContext(context));
    },

    /**
     * Warning logs - ALWAYS logged (production monitoring)
     * Use for: recoverable errors, validation issues, deprecations
     */
    warn: (message, context = {}) => {
        console.warn('[WARN]', message, logger._enrichContext(context));
    },

    /**
     * Error logs - ALWAYS logged (production error tracking)
     * Use for: exceptions, failures, critical issues
     */
    error: (message, error = null, context = {}) => {
        const enrichedContext = logger._enrichContext(context);

        if (error) {
            console.error('[ERROR]', message, {
                ...enrichedContext,
                error: error.message || error,
                stack: error.stack,
                response: error.response?.data
            });
        } else {
            console.error('[ERROR]', message, enrichedContext);
        }
    }
};
