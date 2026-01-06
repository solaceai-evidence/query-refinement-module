import axios from 'axios';
import { authUtils } from '../utils/auth';

const apiClient = axios.create({
    baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
    timeout: parseInt(import.meta.env.VITE_API_TIMEOUT) || 30000,
    headers: {
        'Content-Type': 'application/json'
    }
});

// Request interceptor to add auth token
apiClient.interceptors.request.use(
    (config) => {
        const token = authUtils.getToken();
        if (token && !authUtils.isTokenExpired(token)) {
            config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
    },
    (error) => {
        return Promise.reject(error);
    }
);

// Response interceptor for error handling
apiClient.interceptors.response.use(
    (response) => response,
    async (error) => {
        const originalRequest = error.config;

        // Handle 401 Unauthorized
        if (error.response?.status === 401 && !originalRequest._retry) {
            originalRequest._retry = true;

            // Clear tokens and redirect to login
            authUtils.removeTokens();
            window.location.href = '/login';
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
                await new Promise(resolve => setTimeout(resolve, delay));
                return apiClient(originalRequest);
            }

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
                await new Promise(resolve => setTimeout(resolve, 3000));
                return apiClient(originalRequest);
            }

            return Promise.reject({
                message: 'Service temporarily unavailable. Please try again.',
                status: 503
            });
        }

        // Handle network errors
        if (!error.response) {
            return Promise.reject({
                message: 'Network error. Please check your connection.',
                status: 0
            });
        }

        return Promise.reject(error);
    }
);

export default apiClient;
