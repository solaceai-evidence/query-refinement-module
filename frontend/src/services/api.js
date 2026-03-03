import axios from 'axios';
import { authUtils } from '../utils/auth';
import { logger } from '../utils/logger';
import { toast } from '../utils/toast';

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001';

const apiClient = axios.create({
    baseURL: baseURL,
    timeout: parseInt(import.meta.env.VITE_API_TIMEOUT) || 90000,
    headers: {
        'Content-Type': 'application/json'
    }
});

logger.info('API Client initialized', { baseURL });

// Request interceptor to add auth token
apiClient.interceptors.request.use(
    async (config) => {
        // Skip auth for login and register endpoints
        const isAuthEndpoint = config.url?.includes('/auth/login') || config.url?.includes('/auth/register');

        const token = authUtils.getToken();

        // Skip token check for auth endpoints
        if (isAuthEndpoint) {
            return config;
        }

        // Check if token is expired
        if (token && authUtils.isTokenExpired(token)) {
            logger.warn('Token expired, redirecting to login');
            authUtils.removeTokens();
            window.location.href = '/login?expired=true';
            return Promise.reject(new Error('Token expired'));
        } else if (token) {
            config.headers.Authorization = `Bearer ${token}`;
        }

        return config;
    },
    (error) => {
        logger.error('API request interceptor error', error);
        return Promise.reject(error);
    }
);

// Response interceptor for error handling and request tracing
apiClient.interceptors.response.use(
    (response) => {
        // Extract request_id from response headers for distributed tracing
        const requestId = response.headers['x-request-id'];
        const traceId = response.headers['x-trace-id'];

        // Store request_id in logger context for subsequent logs
        if (requestId) {
            logger.setRequestContext(requestId, traceId);
        }

        // Log successful API calls for production tracing
        logger.debug('API call succeeded', {
            method: response.config.method,
            url: response.config.url,
            status: response.status,
            request_id: requestId,
            trace_id: traceId
        });
        return response;
    },
    async (error) => {
        const originalRequest = error.config;

        // Extract request_id even from error responses for tracing
        const requestId = error.response?.headers?.['x-request-id'];
        const traceId = error.response?.headers?.['x-trace-id'];

        if (requestId) {
            logger.setRequestContext(requestId, traceId);
        }

        // Handle 401 Unauthorized
        // Skip redirect for auth endpoints - a 401 on login means wrong credentials, not expired session
        const isAuthEndpoint = originalRequest.url?.includes('/auth/login') || originalRequest.url?.includes('/auth/register');
        if (error.response?.status === 401 && !originalRequest._retry && !isAuthEndpoint) {
            logger.warn('401 Unauthorized - session expired', {
                url: originalRequest.url,
                request_id: requestId
            });
            originalRequest._retry = true;

            // Clear tokens and redirect to login
            authUtils.removeTokens();
            window.location.href = '/login?expired=true';
            return Promise.reject(error);
        }

        // Handle 429 Rate Limit with retry
        if (error.response?.status === 429) {
            const retryAfter = error.response.headers['retry-after'];
            const delay = retryAfter ? parseInt(retryAfter) * 1000 : 2000;

            // Retry after delay (max 3 retries)
            if (!originalRequest._retryCount) {
                originalRequest._retryCount = 0;
            }

            if (originalRequest._retryCount < 3) {
                originalRequest._retryCount++;

                // Show user-friendly notification
                const delaySeconds = Math.ceil(delay / 1000);
                toast.warning(
                    `Server is busy. Retrying in ${delaySeconds} second${delaySeconds > 1 ? 's' : ''}... (Attempt ${originalRequest._retryCount}/3)`,
                    delay
                );

                logger.warn('Rate limited - retrying', {
                    attempt: originalRequest._retryCount,
                    delay,
                    url: originalRequest.url,
                    request_id: requestId
                });
                await new Promise(resolve => setTimeout(resolve, delay));
                return apiClient(originalRequest);
            }

            logger.error('Rate limit exceeded after retries', null, {
                url: originalRequest.url,
                retries: originalRequest._retryCount,
                request_id: requestId
            });

            // Show final error message to user
            toast.error('Server is too busy right now. Please try again in a few minutes.', 10000);

            return Promise.reject({
                message: 'Rate limit exceeded. Please try again later.',
                status: 429
            });
        }

        // Handle 503 Service Unavailable with retry
        if (error.response?.status === 503) {
            if (!originalRequest._retryCount) {
                originalRequest._retryCount = 0;
            }

            if (originalRequest._retryCount < 2) {
                originalRequest._retryCount++;
                logger.warn('Service unavailable - retrying', {
                    attempt: originalRequest._retryCount,
                    url: originalRequest.url,
                    request_id: requestId
                });
                await new Promise(resolve => setTimeout(resolve, 3000));
                return apiClient(originalRequest);
            }

            logger.error('Service unavailable after retries', null, {
                url: originalRequest.url,
                retries: originalRequest._retryCount,
                request_id: requestId
            });

            return Promise.reject({
                message: 'Service temporarily unavailable. Please try again.',
                status: 503
            });
        }

        // Handle network errors
        if (!error.response) {
            logger.error('Network error', error, {
                url: originalRequest.url,
                request_id: requestId
            });
            return Promise.reject({
                message: 'Network error. Please check your connection.',
                status: 0
            });
        }

        // Log other API errors for production debugging
        logger.error('API call failed', error, {
            method: originalRequest.method,
            url: originalRequest.url,
            status: error.response?.status,
            statusText: error.response?.statusText,
            request_id: requestId,
            trace_id: traceId
        });

        return Promise.reject(error);
    }
);

export default apiClient;
