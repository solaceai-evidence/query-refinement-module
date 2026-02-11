import { useState, useEffect, useRef } from 'react';
import apiClient from '../services/api';
import { logger } from '../utils/logger';

/**
 * Custom hook for polling refinement progress
 * 
 * @param {number|null} queryId - Query ID to track (null to disable polling)
 * @param {number} pollInterval - Polling interval in milliseconds (default: 1500ms)
 * @returns {{
 *   progress: object|null,
 *   isPolling: boolean,
 *   error: string|null,
 *   startPolling: () => void,
 *   stopPolling: () => void
 * }}
 */
export function useProgressTracking(queryId, pollInterval = 1500) {
    const [progress, setProgress] = useState(null);
    const [isPolling, setIsPolling] = useState(false);
    const [error, setError] = useState(null);
    const intervalRef = useRef(null);
    const mountedRef = useRef(true);

    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
            stopPolling();
        };
    }, []);

    const fetchProgress = async () => {
        if (!queryId) return;

        try {
            const response = await apiClient.get(
                `/refinement/queries/${queryId}/progress`
            );

            if (!mountedRef.current) return;

            setProgress(response.data);
            setError(null);

            // Stop polling on terminal states
            const terminalStages = ['completed', 'failed', 'cancelled'];
            if (terminalStages.includes(response.data.stage?.toLowerCase())) {
                logger.info('Progress tracking complete', {
                    queryId,
                    stage: response.data.stage,
                    duration: response.data.elapsed_seconds
                });
                stopPolling();
            }
        } catch (err) {
            if (!mountedRef.current) return;

            const errorMsg = err.response?.data?.detail || err.message;
            logger.warn('Progress fetch failed', {
                queryId,
                error: errorMsg,
                status: err.response?.status
            });

            // Stop polling on 404 (query not found) or 403 (access denied)
            if ([404, 403].includes(err.response?.status)) {
                setError(errorMsg);
                stopPolling();
            }
        }
    };

    const startPolling = () => {
        if (!queryId || isPolling) return;

        logger.info('Starting progress tracking', { queryId, pollInterval });
        setIsPolling(true);
        setError(null);

        // Initial fetch
        fetchProgress();

        // Start polling
        intervalRef.current = setInterval(fetchProgress, pollInterval);
    };

    const stopPolling = () => {
        if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
        }
        setIsPolling(false);
    };

    // Auto-start/stop based on queryId changes
    useEffect(() => {
        if (queryId && !isPolling) {
            startPolling();
        } else if (!queryId && isPolling) {
            stopPolling();
        }

        return () => stopPolling();
    }, [queryId]);

    return {
        progress,
        isPolling,
        error,
        startPolling,
        stopPolling
    };
}
