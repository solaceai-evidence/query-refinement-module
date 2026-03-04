/**
 * Frontend Log Forwarder - Phase 4 Implementation
 * 
 * Buffers and batches frontend logs to send to backend API.
 * Integrates with Phase 2 distributed tracing (request_id/trace_id).
 * 
 * Features:
 * - Automatic batching (up to 100 logs or 30 seconds)
 * - Error tracking with stack traces
 * - Network request monitoring
 * - Performance metrics
 * - User action tracking
 * - Offline queue support
 */

import { getRequestId, getTraceId } from './logger';
import { authUtils } from './auth';

// In production builds, ALWAYS use relative path (same reasoning as api.js).
const API_BASE_URL = import.meta.env.PROD
    ? '/api/v1'
    : (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001/api/v1');
const API_ENDPOINT = `${API_BASE_URL}/logs/frontend`;
const BATCH_SIZE = 100;
const BATCH_INTERVAL_MS = 30000; // 30 seconds
const MAX_QUEUE_SIZE = 500;

class FrontendLogForwarder {
    constructor() {
        this.logQueue = [];
        this.batchTimer = null;
        this.isOnline = navigator.onLine;
        this.sessionId = null;

        // Listen for online/offline events
        window.addEventListener('online', () => this.handleOnline());
        window.addEventListener('offline', () => this.handleOffline());

        // Flush logs before page unload
        window.addEventListener('beforeunload', () => this.flush());

        // Start batch timer
        this.startBatchTimer();

        // Intercept console methods for automatic logging
        if (import.meta.env.PROD) {
            this.interceptConsole();
        }

        // Capture unhandled errors
        this.setupErrorHandlers();

        // Monitor network requests
        this.setupNetworkMonitoring();

        // Track performance metrics
        this.setupPerformanceMonitoring();
    }

    /**
     * Add log to queue
     */
    addLog(level, logType, message, details = {}) {
        const log = {
            timestamp: new Date().toISOString(),
            level,
            log_type: logType,
            message,
            details,
            url: window.location.href,
            user_agent: navigator.userAgent,
            screen_resolution: `${screen.width}x${screen.height}`,
            viewport_size: `${window.innerWidth}x${window.innerHeight}`,
            request_id: getRequestId(),
            trace_id: getTraceId(),
            session_id: this.sessionId,
        };

        // Add to queue
        this.logQueue.push(log);

        // Trim queue if too large
        if (this.logQueue.length > MAX_QUEUE_SIZE) {
            this.logQueue = this.logQueue.slice(-MAX_QUEUE_SIZE);
        }

        // Send immediately if batch is full
        if (this.logQueue.length >= BATCH_SIZE) {
            this.flush();
        }
    }

    /**
     * Add error log with stack trace
     */
    addError(error, context = {}) {
        const log = {
            timestamp: new Date().toISOString(),
            level: 'error',
            log_type: 'error',
            message: error.message || String(error),
            details: { context, ...error },
            url: window.location.href,
            user_agent: navigator.userAgent,
            screen_resolution: `${screen.width}x${screen.height}`,
            viewport_size: `${window.innerWidth}x${window.innerHeight}`,
            request_id: getRequestId(),
            trace_id: getTraceId(),
            session_id: this.sessionId,
            error_name: error.name || 'Error',
            error_stack: error.stack || null,
            error_line: error.lineno || null,
            error_column: error.colno || null,
            error_file: error.filename || null,
        };

        this.logQueue.push(log);

        // Send errors immediately
        this.flush();
    }

    /**
     * Add network request log
     */
    addNetworkLog(url, method, status, durationMs, error = null) {
        const log = {
            timestamp: new Date().toISOString(),
            level: status >= 400 ? 'error' : 'info',
            log_type: 'network',
            message: `${method} ${url} → ${status}`,
            details: { error },
            url: window.location.href,
            user_agent: navigator.userAgent,
            screen_resolution: `${screen.width}x${screen.height}`,
            viewport_size: `${window.innerWidth}x${window.innerHeight}`,
            request_id: getRequestId(),
            trace_id: getTraceId(),
            session_id: this.sessionId,
            network_url: url,
            network_method: method,
            network_status: status,
            network_duration_ms: durationMs,
        };

        this.logQueue.push(log);
    }

    /**
     * Add performance metric
     */
    addPerformanceLog(metric, value) {
        const log = {
            timestamp: new Date().toISOString(),
            level: 'info',
            log_type: 'performance',
            message: `${metric}: ${value}ms`,
            details: {},
            url: window.location.href,
            user_agent: navigator.userAgent,
            screen_resolution: `${screen.width}x${screen.height}`,
            viewport_size: `${window.innerWidth}x${window.innerHeight}`,
            request_id: getRequestId(),
            trace_id: getTraceId(),
            session_id: this.sessionId,
            performance_metric: metric,
            performance_value: value,
        };

        this.logQueue.push(log);
    }

    /**
     * Add user action log
     */
    addUserAction(action, details = {}) {
        const log = {
            timestamp: new Date().toISOString(),
            level: 'info',
            log_type: 'user_action',
            message: action,
            details,
            url: window.location.href,
            user_agent: navigator.userAgent,
            screen_resolution: `${screen.width}x${screen.height}`,
            viewport_size: `${window.innerWidth}x${window.innerHeight}`,
            request_id: getRequestId(),
            trace_id: getTraceId(),
            session_id: this.sessionId,
        };

        this.logQueue.push(log);
    }

    /**
     * Set current session ID
     */
    setSessionId(sessionId) {
        this.sessionId = sessionId;
    }

    /**
     * Flush logs to backend
     */
    async flush() {
        if (this.logQueue.length === 0) {
            return;
        }

        // Don't send if offline
        if (!this.isOnline) {
            console.debug('FrontendLogForwarder: Offline, queueing logs');
            return;
        }

        // Don't send if not authenticated
        const token = authUtils.getToken();
        if (!token) {
            console.debug('FrontendLogForwarder: Not authenticated, skipping log forwarding');
            this.logQueue = []; // Clear queue since we can't send
            return;
        }

        // Take logs from queue
        const logsToSend = this.logQueue.splice(0, BATCH_SIZE);

        try {
            const response = await fetch(API_ENDPOINT, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`,
                },
                body: JSON.stringify({ logs: logsToSend }),
            });

            if (!response.ok) {
                console.error('FrontendLogForwarder: Failed to send logs', response.status);
                // Put logs back at front of queue on failure
                this.logQueue.unshift(...logsToSend);
            } else {
                console.debug(`FrontendLogForwarder: Sent ${logsToSend.length} logs`);
            }
        } catch (error) {
            console.error('FrontendLogForwarder: Error sending logs', error);
            // Put logs back on network error
            this.logQueue.unshift(...logsToSend);
        }
    }

    /**
     * Start batch timer
     */
    startBatchTimer() {
        this.batchTimer = setInterval(() => {
            this.flush();
        }, BATCH_INTERVAL_MS);
    }

    /**
     * Handle online event
     */
    handleOnline() {
        console.log('FrontendLogForwarder: Back online, flushing queued logs');
        this.isOnline = true;
        this.flush();
    }

    /**
     * Handle offline event
     */
    handleOffline() {
        console.log('FrontendLogForwarder: Offline, queueing logs');
        this.isOnline = false;
    }

    /**
     * Intercept console methods
     */
    interceptConsole() {
        const originalConsole = {
            log: console.log,
            warn: console.warn,
            error: console.error,
            info: console.info,
            debug: console.debug,
        };

        // Only intercept in production
        console.log = (...args) => {
            originalConsole.log(...args);
            this.addLog('info', 'console', args.join(' '));
        };

        console.warn = (...args) => {
            originalConsole.warn(...args);
            this.addLog('warn', 'console', args.join(' '));
        };

        console.error = (...args) => {
            originalConsole.error(...args);
            // Don't log console.error twice (already captured by error handlers)
            if (args[0] instanceof Error) {
                return;
            }
            this.addLog('error', 'console', args.join(' '));
        };

        console.info = (...args) => {
            originalConsole.info(...args);
            this.addLog('info', 'console', args.join(' '));
        };

        console.debug = (...args) => {
            originalConsole.debug(...args);
            this.addLog('debug', 'console', args.join(' '));
        };
    }

    /**
     * Setup global error handlers
     */
    setupErrorHandlers() {
        // Catch unhandled errors
        window.addEventListener('error', (event) => {
            this.addError(event.error || {
                message: event.message,
                filename: event.filename,
                lineno: event.lineno,
                colno: event.colno,
            });
        });

        // Catch unhandled promise rejections
        window.addEventListener('unhandledrejection', (event) => {
            this.addError(new Error(event.reason || 'Unhandled promise rejection'), {
                promise: true,
            });
        });
    }

    /**
     * Setup network monitoring
     */
    setupNetworkMonitoring() {
        // Intercept fetch
        const originalFetch = window.fetch;
        window.fetch = async (...args) => {
            const startTime = performance.now();
            const url = typeof args[0] === 'string' ? args[0] : args[0].url;
            const method = args[1]?.method || 'GET';

            try {
                const response = await originalFetch(...args);
                const duration = Math.round(performance.now() - startTime);

                // Don't log our own log forwarding requests
                if (!url.includes('/logs/frontend')) {
                    this.addNetworkLog(url, method, response.status, duration);
                }

                return response;
            } catch (error) {
                const duration = Math.round(performance.now() - startTime);
                this.addNetworkLog(url, method, 0, duration, error.message);
                throw error;
            }
        };

        // Intercept XMLHttpRequest
        const originalXHROpen = XMLHttpRequest.prototype.open;
        const originalXHRSend = XMLHttpRequest.prototype.send;

        XMLHttpRequest.prototype.open = function (method, url, ...args) {
            this._loggedMethod = method;
            this._loggedUrl = url;
            this._loggedStartTime = performance.now();
            return originalXHROpen.apply(this, [method, url, ...args]);
        };

        XMLHttpRequest.prototype.send = function (...args) {
            this.addEventListener('loadend', () => {
                const duration = Math.round(performance.now() - this._loggedStartTime);
                // Don't log our own log forwarding requests
                if (!this._loggedUrl.includes('/logs/frontend')) {
                    logForwarder.addNetworkLog(
                        this._loggedUrl,
                        this._loggedMethod,
                        this.status,
                        duration,
                        this.status >= 400 ? this.statusText : null
                    );
                }
            });
            return originalXHRSend.apply(this, args);
        };
    }

    /**
     * Setup performance monitoring
     */
    setupPerformanceMonitoring() {
        // Capture page load metrics
        window.addEventListener('load', () => {
            setTimeout(() => {
                const perfData = performance.getEntriesByType('navigation')[0];
                if (perfData) {
                    this.addPerformanceLog('page_load', Math.round(perfData.loadEventEnd - perfData.fetchStart));
                    this.addPerformanceLog('dom_content_loaded', Math.round(perfData.domContentLoadedEventEnd - perfData.fetchStart));
                    this.addPerformanceLog('first_paint', Math.round(perfData.responseEnd - perfData.fetchStart));
                }
            }, 0);
        });
    }
}

// Create singleton instance
const logForwarder = new FrontendLogForwarder();

export default logForwarder;

// Export helper functions
export const logError = (error, context) => logForwarder.addError(error, context);
export const logUserAction = (action, details) => logForwarder.addUserAction(action, details);
export const setLogSessionId = (sessionId) => logForwarder.setSessionId(sessionId);
export const flushLogs = () => logForwarder.flush();
