import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import FrameworkSelector from '../components/FrameworkSelector';
import QuestionRenderer from '../components/QuestionRenderer';
import SynthesisResult from '../components/SynthesisResult';
import CommandButtons from '../components/CommandButtons';
import CommandHistoryItem from '../components/CommandHistoryItem';
import ConfirmationDialog from '../components/ConfirmationDialog';
import ProgressIndicator from '../components/ProgressIndicator';
import { refinementService } from '../services/refinement';
import { monitoringService } from '../services/monitoring';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { isCommandResponse, createHistoryItem } from '../types';
import { isUserCommand } from '../constants/commands';
import { logger } from '../utils/logger';
import { setLogSessionId, logUserAction } from '../utils/logForwarder';
import { useProgressTracking } from '../hooks/useProgressTracking';
import './Refinement.css';

/**
 * @typedef {import('../types/api').NextPrompt} NextPrompt
 * @typedef {import('../types/api').ConversationHistoryItem} ConversationHistoryItem
 * @typedef {import('../types/api').CommandResult} CommandResult
 * @typedef {import('../types/api').AspectSummary} AspectSummary
 * @typedef {import('../types/api').SynthesizeQueryResponse} SynthesizeQueryResponse
 */

const Refinement = () => {
    const [stage, setStage] = useState('framework-selection'); // framework-selection, initial-query, refinement, review, synthesis
    const [selectedFramework, setSelectedFramework] = useState(null);
    const [initialQuery, setInitialQuery] = useState('');
    const [sessionId, setSessionId] = useState(null);
    const [queryId, setQueryId] = useState(null);
    const [currentQuestion, setCurrentQuestion] = useState(null);
    const [currentAspectId, setCurrentAspectId] = useState(null);
    const [aspects, setAspects] = useState([]);
    const [synthesis, setSynthesis] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [conversationHistory, setConversationHistory] = useState([]);
    const [commandResult, setCommandResult] = useState(null);
    const [readyForSynthesis, setReadyForSynthesis] = useState(false);
    const [confirmationDialog, setConfirmationDialog] = useState({
        isOpen: false,
        title: '',
        message: '',
        onConfirm: null,
        type: 'warning'
    });
    const { logout } = useAuth();
    const navigate = useNavigate();
    const { showSuccess, showInfo, showWarning, showError } = useToast();

    // Progress tracking hook
    const { progress, isPolling } = useProgressTracking(queryId);

    // Check for saved session but don't auto-restore
    const [savedSessionData, setSavedSessionData] = useState(null);
    const [userStatus, setUserStatus] = useState(null);
    const [workflowLimitReached, setWorkflowLimitReached] = useState(false);

    useEffect(() => {
        console.log('[Refinement] Component mounted, checking for saved session...');
        const savedSession = localStorage.getItem('refinement_session');
        console.log('[Refinement] localStorage content:', savedSession);

        if (savedSession) {
            try {
                const session = JSON.parse(savedSession);

                // Validate session data structure
                if (!session.sessionId || !session.queryId || !session.framework) {
                    console.warn('[Refinement] Invalid session data structure, clearing...');
                    logger.warn('Invalid saved session structure', { session });
                    localStorage.removeItem('refinement_session');
                    return;
                }

                // Check if session is too old (expired after 8 hours)
                const sessionAge = session.timestamp ? Date.now() - session.timestamp : Infinity;
                const MAX_SESSION_AGE = 8 * 60 * 60 * 1000; // 8 hours

                if (sessionAge > MAX_SESSION_AGE) {
                    console.warn('[Refinement] Session expired (older than 8 hours), clearing...');
                    logger.warn('Saved session expired', { age: sessionAge, maxAge: MAX_SESSION_AGE });
                    localStorage.removeItem('refinement_session');
                    return;
                }

                console.log('[Refinement] Found valid saved session:', session);
                logger.info('Found saved session', { sessionId: session.sessionId, queryId: session.queryId });

                // Validate session exists on backend before showing restore option
                validateAndSetSession(session);
            } catch (e) {
                console.error('[Refinement] Failed to parse saved session:', e);
                logger.error('Failed to parse saved session', e);
                localStorage.removeItem('refinement_session');
            }
        } else {
            console.log('[Refinement] No saved session found in localStorage');
        }

        // Check user workflow status
        const checkUserStatus = async () => {
            try {
                const response = await refinementService.getUserStatus();
                setUserStatus(response);
                if (!response.can_start_new_workflow) {
                    setWorkflowLimitReached(true);
                }
            } catch (err) {
                logger.error('Failed to check user status', err);
            }
        };
        checkUserStatus();
    }, []);

    // Validate session exists on backend before offering restoration
    const validateAndSetSession = async (session) => {
        try {
            // Quick check if session still exists on backend
            await refinementService.getStatus(session.queryId);
            // If successful, session is valid
            setSavedSessionData(session);
        } catch (err) {
            // Session no longer exists on backend
            if (err.response?.status === 404) {
                console.warn('[Refinement] Saved session no longer exists on backend');
                logger.warn('Saved session not found on backend', {
                    sessionId: session.sessionId,
                    queryId: session.queryId
                });
                localStorage.removeItem('refinement_session');
            } else {
                // Other error - still show restore option, let user try
                logger.warn('Could not validate session, showing restore option anyway', err);
                setSavedSessionData(session);
            }
        }
    };

    // Save session to localStorage
    const saveSession = (sessionData) => {
        console.log('[Refinement] Saving session to localStorage:', sessionData);
        // Add timestamp for expiration checking
        const sessionWithTimestamp = {
            ...sessionData,
            timestamp: Date.now()
        };
        localStorage.setItem('refinement_session', JSON.stringify(sessionWithTimestamp));
        console.log('[Refinement] Session saved. Verification:', localStorage.getItem('refinement_session'));
    };

    const clearSession = () => {
        console.log('[Refinement] Clearing session from localStorage');
        localStorage.removeItem('refinement_session');
    };

    // ==========================================
    // Helper Functions - Error Handling & Health Checks
    // ==========================================

    /**
     * Check service health quietly (non-blocking warning)
     */
    const checkServiceHealthQuietly = async () => {
        try {
            const health = await monitoringService.getLLMHealth();
            if (health.overall_health === 'degraded') {
                showWarning(
                    'LLM services are currently experiencing issues. ' +
                    'Operations may take longer or require retries.'
                );
            }
        } catch (err) {
            // Silently ignore - monitoring is optional
            logger.debug('Service health check failed (non-critical)', err);
        }
    };

    /**
     * Enhanced error handler with circuit breaker diagnostics
     * @param {Error} error - The error object
     * @param {string} operation - Description of failed operation
     * @returns {Promise<string>} - User-friendly error message
     */
    const handleRefinementError = async (error, operation = 'operation') => {
        const status = error.response?.status;
        const baseDetail = error.response?.data?.detail || error.message;

        // Check for LLM-related errors
        if (status === 503 || status === 502 || baseDetail?.toLowerCase().includes('llm')) {
            try {
                const health = await monitoringService.getLLMHealth();

                if (health.overall_health === 'degraded') {
                    const degradedProviders = Object.entries(health.providers || {})
                        .filter(([_, data]) => !data.is_healthy)
                        .map(([name]) => name);

                    logger.error(`${operation} failed due to LLM service issues`, {
                        degradedProviders,
                        status
                    });

                    return (
                        `Unable to ${operation} - LLM services are temporarily unavailable. ` +
                        `Affected providers: ${degradedProviders.join(', ')}. ` +
                        `Please try again in a few moments.`
                    );
                }
            } catch (healthErr) {
                logger.debug('Could not check LLM health during error handling', healthErr);
            }
        }

        // Check for rate limiting
        if (status === 429) {
            return `Rate limit exceeded. Please wait a moment before trying again.`;
        }

        // Check for authentication issues
        if (status === 401 || status === 403) {
            return `Authentication error. Please log in again.`;
        }

        // Check for validation errors
        if (status === 400 || status === 422) {
            return baseDetail || `Invalid request. Please check your input and try again.`;
        }

        // Generic fallback
        return baseDetail || `Failed to ${operation}. Please try again.`;
    };

    // ==========================================
    // Event Handlers
    // ==========================================

    const handleFrameworkSelect = (framework) => {
        if (workflowLimitReached) {
            setError('You have already completed one workflow. Thank you for your participation!');
            return;
        }
        setSelectedFramework(framework);
        setStage('initial-query');
    };

    const handleInitialQuerySubmit = async (e) => {
        e.preventDefault();
        if (!initialQuery.trim()) return;

        setLoading(true);
        setError(null);

        try {
            // Check LLM health before starting (non-blocking)
            try {
                const health = await monitoringService.getLLMHealth();
                if (health.overall_health === 'degraded') {
                    showWarning(
                        'LLM services are experiencing issues. Your refinement may take longer than usual or require retries.'
                    );
                    logger.warn('Starting refinement with degraded LLM health', { health });
                }
            } catch (healthErr) {
                // Don't block if monitoring is unavailable
                logger.debug('Health check unavailable, proceeding anyway', healthErr);
            }

            logger.info('Starting refinement session', {
                framework: selectedFramework,
                queryLength: initialQuery.length
            });

            const response = await refinementService.startRefinement(
                selectedFramework,
                initialQuery
            );

            setSessionId(response.session_id);
            setQueryId(response.query_id);

            // Set session ID for log forwarder
            setLogSessionId(response.session_id);

            logger.info('Refinement session started', {
                sessionId: response.session_id,
                queryId: response.query_id,
                aspectCount: response.summary?.aspects?.length || 0
            });

            // Log user action
            logUserAction('session_started', {
                framework: selectedFramework,
                query_length: initialQuery.length,
                aspect_count: response.summary?.aspects || 0
            });

            // Validate question exists
            if (response.next_prompt && !response.next_prompt.question) {
                console.warn('[Refinement] Question is missing from next_prompt, may show fallback text', {
                    aspectId: response.next_prompt.aspect_id,
                    name: response.next_prompt.name
                });
            }

            setCurrentQuestion(response.next_prompt);
            setCurrentAspectId(response.next_prompt?.aspect_id);
            setAspects(response.summary?.aspects || []);

            // Check if all aspects are immediately complete (ready for synthesis)
            if (response.ready_for_synthesis && !response.next_prompt) {
                logger.info('All aspects complete immediately - ready for manual synthesis');
                setReadyForSynthesis(true);
                setStage('review');
                showSuccess('All dimensions complete! Review your answers and click "Generate Refined Query" to proceed.');
            } else {
                setStage('refinement');
            }

            // Save session
            const sessionData = {
                sessionId: response.session_id,
                queryId: response.query_id,
                framework: selectedFramework
            };
            saveSession(sessionData);

            // Add to conversation history - both initial query and first question
            setConversationHistory([
                {
                    type: 'query',
                    content: initialQuery
                },
                ...(response.next_prompt?.question ? [{
                    type: 'question',
                    content: response.next_prompt.question,
                    aspectId: response.next_prompt.aspect_id,
                    aspectName: response.next_prompt.name,
                    timestamp: new Date().toISOString()
                }] : [])
            ]);
        } catch (err) {
            logger.error('Failed to start refinement', err, { framework: selectedFramework });

            // Enhanced error handling with circuit breaker check
            const errorDetail = await handleRefinementError(err, 'start refinement');
            setError(errorDetail);
        } finally {
            setLoading(false);
        }
    };

    /**
     * Handle user answer or command submission
     * @param {string} answer - User's answer or command
     * @returns {Promise<void>}
     */
    const handleAnswer = async (answer) => {
        const isCommand = isUserCommand(answer);

        logger.debug('handleAnswer called', { answer, isCommand, sessionId, queryId });

        // Handle /restart command locally without calling backend
        if (answer.trim() === '/restart') {
            logger.info('Restart command - clearing local state');
            handleStartOver();
            return;
        }

        // Validate required data
        if (!sessionId || !queryId) {
            logger.error('Missing session or query ID', null, { sessionId, queryId });
            setError('Session not initialized. Please start a new refinement.');
            return;
        }

        // Quick health check for circuit breaker issues (non-blocking)
        checkServiceHealthQuietly();

        setLoading(true);
        setError(null);
        setCommandResult(null); // Clear any previous command result

        try {
            // For commands, add to history immediately. For answers, wait until we have the next question.
            if (isCommand) {
                setConversationHistory(prev => [...prev,
                createHistoryItem('command', answer, { aspectId: currentAspectId })
                ]);
            }

            const response = await refinementService.continueRefinement(
                sessionId,
                queryId,
                answer
            );

            console.log('[TRACE] ========== RAW RESPONSE ==========');
            console.log('[TRACE] Response received, type:', typeof response);
            console.log('[TRACE] Response keys:', Object.keys(response || {}));
            console.log('[TRACE] Full response:', JSON.stringify(response, null, 2));
            console.log('[TRACE] =====================================');

            // Check if this is a command response using type guard
            const isCmd = isCommandResponse(response);
            console.log('[TRACE] isCommandResponse returned:', isCmd);

            if (isCmd) {
                logger.info('Command executed', {
                    commandType: response.command_type,
                    success: response.success,
                    hasNextPrompt: !!response.next_prompt
                });

                console.log('[COMMAND] Full response:', JSON.stringify(response, null, 2));

                /** @type {CommandResult} */
                const commandResultData = {
                    type: response.command_type,
                    message: response.message,
                    success: response.success,
                    step_summary: response.step_summary,
                    step_list: response.step_list,
                    invalidated_aspects: response.invalidated_aspects
                };

                console.log('[COMMAND RESPONSE] Setting command result:', JSON.stringify(commandResultData, null, 2));
                console.log('[COMMAND RESPONSE] step_summary exists?', !!response.step_summary);
                console.log('[COMMAND RESPONSE] step_summary value:', response.step_summary);

                // Add command result to history
                setConversationHistory(prev => {
                    // Update the last command entry with the result
                    const newHistory = [...prev];
                    const lastCommandIndex = newHistory.length - 1;
                    if (newHistory[lastCommandIndex]?.type === 'command') {
                        newHistory[lastCommandIndex].result = commandResultData;
                        console.log('[COMMAND TRACE] Updated command in history with result');
                    }
                    return newHistory;
                });

                // Only update question if command provides next_prompt
                console.log('[COMMAND RESPONSE] Checking for next_prompt...');
                console.log('[COMMAND RESPONSE] response.next_prompt exists?', !!response.next_prompt);
                console.log('[COMMAND RESPONSE] response.next_prompt value:', response.next_prompt);

                if (response.next_prompt) {
                    try {
                        console.log('[COMMAND RESPONSE] next_prompt exists:', response.next_prompt);
                        console.log('[COMMAND RESPONSE] next_prompt.question:', response.next_prompt.question);
                        console.log('[COMMAND RESPONSE] next_prompt.aspect_id:', response.next_prompt.aspect_id);
                        console.log('[COMMAND RESPONSE] Current question before update:', currentQuestion);
                    } catch (e) {
                        console.error('[COMMAND RESPONSE] Error logging next_prompt:', e);
                    }

                    // Only update if next_prompt has a valid question
                    if (response.next_prompt.question) {
                        // Only add to history if question is different from current
                        const isDifferentQuestion = !currentQuestion ||
                            response.next_prompt.question !== currentQuestion.question;

                        console.log('[COMMAND RESPONSE] isDifferentQuestion:', isDifferentQuestion);

                        if (isDifferentQuestion) {
                            console.log('[COMMAND RESPONSE] Adding new question to history');
                            console.log('[COMMAND RESPONSE] Question preview:', response.next_prompt.question.substring(0, 100));

                            setConversationHistory(prev => [...prev,
                            createHistoryItem('question', response.next_prompt.question, {
                                aspectId: response.next_prompt.aspect_id,
                                aspectName: response.next_prompt.name
                            })
                            ]);
                        } else {
                            console.log('[COMMAND RESPONSE] Same question - not adding to history');
                        }

                        console.log('[COMMAND RESPONSE] Updating current question state');
                        setCurrentQuestion(response.next_prompt);
                        setCurrentAspectId(response.next_prompt.aspect_id);

                        // Transition back to refinement stage if we were in review
                        if (stage === 'review') {
                            setStage('refinement');
                            setReadyForSynthesis(false);
                        }
                    } else {
                        // next_prompt exists but question is null - preserve current state
                        console.log('[COMMAND RESPONSE] next_prompt.question is null - preserving current state');
                        // Don't update currentQuestion or currentAspectId
                    }
                } else {
                    // No next_prompt in response - check command behavior
                    console.log('[COMMAND RESPONSE] No next_prompt in response');
                    console.log('[COMMAND RESPONSE] Command type:', response.command_type);
                    console.log('[COMMAND RESPONSE] Command answer:', answer);

                    const { isInformationalCommand } = await import('../constants/commands');
                    const isInfoCommand = isInformationalCommand(answer);

                    console.log('[COMMAND RESPONSE] Is informational?', isInfoCommand);

                    if (isInfoCommand) {
                        // Informational commands don't change flow state - keep current question
                        console.log('[COMMAND RESPONSE] Informational command - preserving current question');
                        // currentQuestion and currentAspectId remain unchanged
                    } else {
                        // Navigation/control commands without next_prompt
                        console.warn('[COMMAND RESPONSE] ⚠️ No next_prompt for non-informational command');
                        console.warn('[COMMAND RESPONSE] This might mean:');
                        console.warn('[COMMAND RESPONSE]   1. All dimensions are complete (check synthesis_ready flag)');
                        console.warn('[COMMAND RESPONSE]   2. Backend error generating next dimension');
                        console.warn('[COMMAND RESPONSE]   3. No more dimensions available');

                        // Check if we should trigger synthesis
                        if (response.synthesis_ready) {
                            console.log('[COMMAND RESPONSE] synthesis_ready=true, will trigger synthesis');
                        } else {
                            console.error('[COMMAND RESPONSE] ❌ Command succeeded but no next_prompt and not ready for synthesis');
                            showError('Unable to load next dimension. Please try again or contact support.');
                        }
                    }
                }

                // Check if confirmation is needed (force_required flag)
                if (response.force_required && response.invalidated_aspects?.length > 0) {
                    const confirmed = window.confirm(
                        `${response.message}\n\nAffected aspects: ${response.invalidated_aspects.join(', ')}\n\nDo you want to proceed?`
                    );

                    if (confirmed) {
                        // Re-submit command with force=true
                        console.log('[COMMAND] Re-submitting with force=true');
                        const forceResponse = await refinementService.continueRefinement(
                            sessionId,
                            queryId,
                            answer,
                            true // force flag
                        );
                        // Process the forced response (recursive call would be cleaner but this avoids complexity)
                        if (forceResponse.next_prompt?.question) {
                            setCurrentQuestion(forceResponse.next_prompt);
                            setCurrentAspectId(forceResponse.next_prompt.aspect_id);
                        }
                    }
                }

                // Check if synthesis is ready (/submit command)
                if (response.synthesis_ready) {
                    console.log('[COMMAND RESPONSE] synthesis_ready flag detected - triggering synthesis');
                    logger.info('Synthesis requested via /submit command');
                    showInfo('Generating your refined query...');
                    await handleSynthesis();
                    return; // Exit early, synthesis will handle its own state
                }

                // Show toast notifications for command results
                if (response.success) {
                    const { isInformationalCommand } = await import('../constants/commands');
                    const isInfoCmd = isInformationalCommand(answer);

                    if (isInfoCmd) {
                        // Informational commands - show info toast
                        if (response.command_type === 'status') {
                            showInfo('Progress updated');
                        } else if (response.command_type === 'steps') {
                            showInfo('Steps listed');
                        }
                    } else {
                        // Navigation/Control commands - show success toast with details
                        if (response.command_type === 'skip') {
                            showSuccess('Dimension skipped - moving to next');
                        } else if (response.command_type === 'done') {
                            showSuccess('Dimension completed - moving to next');
                        } else if (response.command_type === 'clear') {
                            showSuccess('Dimension cleared - question regenerated');
                            // Clear OLD conversation history for the current dimension
                            // Keep: /clear command, new question (added earlier at line 365), items from other dimensions
                            // Remove: Old Q&A for this dimension that appear BEFORE the /clear command
                            console.log('[CLEAR COMMAND] Clearing old conversation history for aspectId:', currentAspectId);
                            setConversationHistory(prev => {
                                // Find the /clear command index
                                const clearCmdIdx = prev.findIndex((item, idx) =>
                                    item.type === 'command' &&
                                    item.content.trim() === '/clear' &&
                                    // Use a recent index (commands are added to end)
                                    idx >= prev.length - 5
                                );

                                if (clearCmdIdx === -1) {
                                    console.warn('[CLEAR COMMAND] Could not find /clear command in history');
                                    return prev;
                                }

                                // Keep everything except old Q&A for this dimension before /clear command
                                const filtered = prev.filter((item, idx) => {
                                    // Keep everything at or after /clear command
                                    if (idx >= clearCmdIdx) return true;
                                    // Keep items from other dimensions
                                    if (item.aspectId !== currentAspectId) return true;
                                    // Remove old Q&A for this dimension (before /clear)
                                    return false;
                                });

                                console.log('[CLEAR COMMAND] Before:', prev.length, 'After:', filtered.length, 'Removed:', prev.length - filtered.length);
                                return filtered;
                            });
                        } else if (response.command_type === 'back' || response.command_type === 'prev') {
                            const cleared = response.invalidated_aspects?.length || 0;
                            showSuccess(`Moved back - ${cleared} dimension(s) will be regenerated`);
                        } else if (response.command_type === 'restart') {
                            showSuccess('Session restarted');
                        }
                    }
                } else {
                    // Command failed - show error
                    showError(response.message || 'Command failed');
                }

                // Update aspect status from command response data or fetch if needed
                if (response.step_summary) {
                    // Use data from command response (avoid redundant API call)
                    console.log('[COMMAND RESPONSE] Updating aspects from step_summary');
                    // Extract aspects from step_summary if available
                    // For now, only fetch if it's not an informational command
                    const { isInformationalCommand } = await import('../constants/commands');
                    if (!isInformationalCommand(answer)) {
                        await updateAspectStatus();
                    }
                } else {
                    // No summary in response, fetch fresh data
                    await updateAspectStatus();
                }
            } else {
                console.log('[TRACE] Regular answer response (not a command)');

                // Regular answer response - add answer and next question together
                if (response.next_prompt) {
                    // Validate question exists
                    if (!response.next_prompt.question) {
                        console.warn('[Refinement] Question missing in answer response', {
                            aspectId: response.next_prompt.aspect_id,
                            aspectName: response.next_prompt.name
                        });
                    }

                    if (response.next_prompt.question) {
                        console.log('[TRACE] Adding answer and next question to history together');
                        setConversationHistory(prev => [...prev,
                        // Add the answer first
                        createHistoryItem('answer', answer, { aspectId: currentAspectId }),
                        // Then add the next question
                        createHistoryItem('question', response.next_prompt.question, {
                            aspectId: response.next_prompt.aspect_id,
                            aspectName: response.next_prompt.name
                        })
                        ]);
                    } else {
                        console.warn('[TRACE] next_prompt.question is null or empty - adding answer only');
                        // Add answer even if no question follows
                        setConversationHistory(prev => [...prev,
                        createHistoryItem('answer', answer, { aspectId: currentAspectId })
                        ]);
                    }
                    setCurrentQuestion(response.next_prompt);
                    setCurrentAspectId(response.next_prompt.aspect_id);

                    // Transition back to refinement stage if we were in review
                    if (stage === 'review') {
                        setStage('refinement');
                        setReadyForSynthesis(false);
                    }

                    // Show success toast for answer submitted
                    showSuccess('Answer submitted');
                } else {
                    console.log('[TRACE] No next_prompt - checking ready_for_synthesis flag');
                    // Add answer before synthesis
                    setConversationHistory(prev => [...prev,
                    createHistoryItem('answer', answer, { aspectId: currentAspectId })
                    ]);
                    setCurrentQuestion(null);
                    setCurrentAspectId(null);

                    // Check ready_for_synthesis flag
                    if (response.ready_for_synthesis) {
                        logger.info('All aspects complete - ready for manual synthesis');
                        setReadyForSynthesis(true);
                        setStage('review');
                        showSuccess('All dimensions complete! Review your answers and click "Generate Refined Query" to proceed.');
                    }
                }

                // Fetch updated status to refresh aspects
                await updateAspectStatus();
            }
        } catch (err) {
            console.error('[ERROR] ========== CATCH BLOCK ==========');
            console.error('[ERROR] Error in handleAnswer:', err);
            console.error('[ERROR] Error message:', err.message);
            console.error('[ERROR] Error response:', err.response);
            console.error('[ERROR] Error response data:', err.response?.data);
            console.error('[ERROR] ======================================');

            // Enhanced error handling with circuit breaker check
            const errorDetail = await handleRefinementError(err, 'process answer');
            setError(errorDetail);
        } finally {
            console.log('[TRACE] handleAnswer complete, setting loading to false');
            setLoading(false);
        }
    };

    /**
     * Update aspect status from API
     * @returns {Promise<void>}
     */
    const updateAspectStatus = async () => {
        if (!queryId) return;
        try {
            const status = await refinementService.getStatus(queryId);
            setAspects(status.aspects_summary?.aspects || []);
        } catch (err) {
            // Silently fail - status updates are non-critical
            // Just log to console, don't block user interaction
            console.warn('Failed to update aspect status (non-critical):', err.message);
            logger.debug('Status update failed', { queryId, error: err.message });
        }
    };

    /**
     * Handle command button click
     * @param {string} command - Command string (e.g., "/skip")
     * @returns {Promise<void>}
     */
    const handleCommand = async (command) => {
        console.log('[COMMAND HANDLER] User clicked command:', command);
        console.log('[COMMAND HANDLER] Current sessionId:', sessionId);
        console.log('[COMMAND HANDLER] Current queryId:', queryId);
        console.log('[COMMAND HANDLER] Current aspectId:', currentAspectId);

        const cmdTrimmed = command.trim();

        // Special handling for /skip command - confirm if there's existing data
        if (cmdTrimmed === '/skip') {
            // Check if there are any answers for the current dimension in history
            const currentDimensionAnswers = conversationHistory.filter(
                item => item.type === 'answer' && item.aspectId === currentAspectId
            );

            if (currentDimensionAnswers.length > 0) {
                // Dimension has answers - show confirmation dialog
                const dimensionName = currentQuestion?.name || 'this dimension';

                setConfirmationDialog({
                    isOpen: true,
                    title: 'Skip Dimension?',
                    message: `Skipping "${dimensionName}" will remove all ${currentDimensionAnswers.length} answer(s) you've already provided for this dimension.\n\nDo you want to continue?`,
                    type: 'warning',
                    onConfirm: async () => {
                        console.log('[COMMAND HANDLER] Skip confirmed by user');
                        setConfirmationDialog({ ...confirmationDialog, isOpen: false });
                        // Set loading before calling handleAnswer (it also sets loading, but be explicit)
                        setLoading(true);
                        await handleAnswer(command);
                    }
                });
                return; // Wait for user confirmation
            }
        }

        // Confirmation for /restart command
        if (cmdTrimmed === '/restart') {
            const completedCount = conversationHistory.filter(item => item.type === 'answer').length;
            if (completedCount > 0) {
                setConfirmationDialog({
                    isOpen: true,
                    title: 'Restart Session?',
                    message: `This will clear all progress and start from the beginning.\n\nYou have provided ${completedCount} answer(s) so far.\n\nDo you want to restart?`,
                    type: 'warning',
                    onConfirm: async () => {
                        console.log('[COMMAND HANDLER] Restart confirmed by user');
                        setConfirmationDialog({ ...confirmationDialog, isOpen: false });
                        setLoading(true);
                        await handleAnswer(command);
                        showInfo('Session restarted');
                    }
                });
                return;
            }
        }

        // Confirmation for /back command
        if (cmdTrimmed === '/back' || cmdTrimmed === '/prev' || cmdTrimmed === '/previous') {
            const activeIdx = aspects.findIndex(a => a.is_active);
            if (activeIdx > 0) {
                const currentDimension = aspects[activeIdx]?.aspect_name || 'current dimension';
                const previousDimension = aspects[activeIdx - 1]?.aspect_name || 'previous dimension';

                setConfirmationDialog({
                    isOpen: true,
                    title: 'Go Back?',
                    message: `Going back will:\n• Clear "${previousDimension}" for fresh review\n• Remove "${currentDimension}" and all subsequent dimensions\n\nThey will be regenerated based on your updated answers.\n\nDo you want to go back?`,
                    type: 'warning',
                    onConfirm: async () => {
                        console.log('[COMMAND HANDLER] Back confirmed by user');
                        setConfirmationDialog({ ...confirmationDialog, isOpen: false });
                        setLoading(true);
                        showInfo('Processing...');
                        await handleAnswer(command);
                    }
                });
                return;
            }
        }

        // Confirmation for /submit command
        if (cmdTrimmed === '/submit' || cmdTrimmed === '/end') {
            const completedDimensions = aspects.filter(a => a.status === 'completed').length;
            const totalDimensions = aspects.length;

            setConfirmationDialog({
                isOpen: true,
                title: 'Generate Final Query?',
                message: `Ready to generate your refined query?\n\n${completedDimensions} of ${totalDimensions} dimension(s) completed.\n\nYou can continue refining or generate now with current answers.`,
                type: 'info',
                onConfirm: async () => {
                    console.log('[COMMAND HANDLER] Submit confirmed by user');
                    setConfirmationDialog({ ...confirmationDialog, isOpen: false });
                    setLoading(true);
                    await handleAnswer(command);
                }
            });
            return;
        }

        // Commands are handled through handleAnswer
        await handleAnswer(command);
    };

    /**
     * Request synthesis of refined query
     * @returns {Promise<void>}
     */
    const handleSynthesis = async () => {
        if (!queryId || !sessionId) {
            console.error('[handleSynthesis] Missing queryId or sessionId', { queryId, sessionId });
            setError('Cannot synthesize: Missing session information');
            return;
        }

        console.log('[handleSynthesis] Starting synthesis', { queryId, sessionId });
        setLoading(true);
        setError(null);

        try {
            const result = await refinementService.getSynthesis(queryId);
            console.log('[handleSynthesis] Raw result received:', result);
            console.log('[handleSynthesis] Result type:', typeof result);
            console.log('[handleSynthesis] Result keys:', result ? Object.keys(result) : 'null');
            console.log('[handleSynthesis] integrated_statement:', result?.integrated_statement);
            console.log('[handleSynthesis] integrated_statement type:', typeof result?.integrated_statement);
            console.log('[handleSynthesis] structured_output:', result?.structured_output);

            // Validate result object exists
            if (!result || typeof result !== 'object') {
                console.error('[handleSynthesis] Invalid result format:', result);
                throw new Error('Invalid synthesis response format - expected object, got ' + typeof result);
            }

            // Check if integrated_statement exists and is non-empty
            if (!result.integrated_statement || typeof result.integrated_statement !== 'string') {
                console.error('[handleSynthesis] Missing or invalid integrated_statement:', {
                    integrated_statement: result.integrated_statement,
                    type: typeof result.integrated_statement
                });
                throw new Error('Synthesis response missing integrated_statement field');
            }

            // Check if integrated_statement is just whitespace
            if (result.integrated_statement.trim().length === 0) {
                console.error('[handleSynthesis] integrated_statement is empty or whitespace');
                throw new Error('Synthesis returned empty statement');
            }

            console.log('[handleSynthesis] Integrated statement length:', result.integrated_statement.length);
            console.log('[handleSynthesis] First 200 chars:', result.integrated_statement.substring(0, 200));

            // Check for truncated JSON in integrated_statement
            if (result.integrated_statement &&
                typeof result.integrated_statement === 'string' &&
                (result.integrated_statement.includes('```json') || result.integrated_statement.startsWith('{'))) {
                console.warn('[handleSynthesis] ⚠️ Synthesis returned raw JSON instead of parsed result');

                // Try to extract integrated_statement from the JSON string
                try {
                    // Remove markdown fences
                    let jsonStr = result.integrated_statement.replace(/```json\n?/g, '').replace(/```\n?$/g, '');

                    // Check if truncated
                    if (!jsonStr.trim().endsWith('}')) {
                        console.error('[handleSynthesis] ❌ JSON response is truncated!');
                        console.error('[handleSynthesis] Last 100 chars:', jsonStr.slice(-100));
                        setError('The synthesis response was incomplete. This usually means the LLM response was too long. Please try again or contact support.');
                        return;
                    }

                    const parsed = JSON.parse(jsonStr);
                    console.log('[handleSynthesis] Parsed JSON keys:', Object.keys(parsed));

                    if (parsed.integrated_statement) {
                        result.integrated_statement = parsed.integrated_statement;
                        result.structured_output = parsed;
                        console.log('[handleSynthesis] ✓ Successfully extracted integrated_statement:', result.integrated_statement.substring(0, 100));
                    } else {
                        console.warn('[handleSynthesis] No integrated_statement in parsed JSON');
                    }
                } catch (parseErr) {
                    console.error('[handleSynthesis] Failed to parse JSON from integrated_statement:', parseErr);
                    setError('The synthesis response could not be processed. Please try again.');
                    return;
                }
            }

            console.log('[handleSynthesis] ✓ Setting synthesis result');
            setSynthesis(result);
            console.log('[handleSynthesis] ✓ Changing stage to synthesis');
            setStage('synthesis');
            console.log('[handleSynthesis] ✓ Clearing session');
            clearSession(); // Clear saved session after completion

            // Show success toast
            showSuccess('Your refined query has been generated!');

            console.log('[handleSynthesis] ✓ Synthesis complete and displayed');
        } catch (err) {
            console.error('[handleSynthesis] Synthesis error:', err);
            console.error('[handleSynthesis] Error name:', err.name);
            console.error('[handleSynthesis] Error message:', err.message);
            console.error('[handleSynthesis] Error response:', err.response?.data);
            console.error('[handleSynthesis] Error status:', err.response?.status);

            // Enhanced error handling with circuit breaker check
            const errorDetail = await handleRefinementError(err, 'synthesize query');
            setError(errorDetail);
        } finally {
            setLoading(false);
            console.log('[handleSynthesis] Loading state cleared');
        }
    };

    const handleResumeSession = async () => {
        console.log('[Refinement] handleResumeSession called');
        console.log('[Refinement] savedSessionData:', savedSessionData);
        console.log('[Refinement] localStorage before resume:', localStorage.getItem('refinement_session'));

        if (!savedSessionData) return;

        setLoading(true);
        try {
            // Restore session state
            setSessionId(savedSessionData.sessionId);
            setQueryId(savedSessionData.queryId);
            setSelectedFramework(savedSessionData.framework);
            setLogSessionId(savedSessionData.sessionId);

            // Fetch current status from API
            const status = await refinementService.getStatus(savedSessionData.queryId);
            console.log('[Refinement] Status received:', status);

            logger.info('Session resumed', {
                sessionId: savedSessionData.sessionId,
                queryId: savedSessionData.queryId,
                stage: status.ready_for_synthesis ? 'synthesis' : 'refinement'
            });

            // Restore initial query
            if (status.original_query) {
                setInitialQuery(status.original_query);
            }

            // Set aspects
            setAspects(status.aspects || []);

            // Restore conversation history
            if (status.conversation_history && status.conversation_history.length > 0) {
                logger.info('Restoring conversation history', {
                    historyLength: status.conversation_history.length
                });
                setConversationHistory(status.conversation_history);
            }

            // Check if ready for synthesis
            if (status.ready_for_synthesis && !status.next_prompt) {
                setReadyForSynthesis(true);
                setStage('review');
                showSuccess('All dimensions complete! Review your answers and click "Generate Refined Query" to proceed.');
            } else {
                setCurrentQuestion(status.next_prompt);
                setCurrentAspectId(status.next_prompt?.aspect_id);
                setStage('refinement');

                // Keep session in localStorage so it can be resumed after refresh
                // It will be cleared when synthesis completes or user starts over
                console.log('[Refinement] Keeping session in localStorage for future refreshes');
            }

            // Clear the saved session notification but keep localStorage
            setSavedSessionData(null);
            console.log('[Refinement] Cleared savedSessionData state but kept localStorage');
            console.log('[Refinement] localStorage after resume:', localStorage.getItem('refinement_session'));
        } catch (err) {
            console.error('[Refinement] Resume session failed:', err);
            logger.error('Failed to resume session', err);
            setError('Failed to resume session. Please start a new one.');
            clearSession();
            setSavedSessionData(null);
        } finally {
            setLoading(false);
        }
    };

    const handleStartOver = async () => {
        console.log('[Refinement] handleStartOver called - clearing all state');
        console.log('[Refinement] Current sessionId:', sessionId);
        console.log('[Refinement] Stack trace:', new Error().stack);

        // If we have a session ID, abandon it on the backend to clean up database
        if (sessionId) {
            try {
                console.log('[Refinement] Attempting to abandon session', sessionId);
                await refinementService.abandonSession(sessionId);
                console.log('[Refinement] Session abandoned successfully');
                logger.info('Session abandoned', { sessionId });
            } catch (error) {
                // Log but don't block the UI reset
                console.error('[Refinement] Failed to abandon session:', error);
                logger.error('Failed to abandon session', error, { sessionId });
                // Continue with UI reset anyway
            }
        }

        // Clear local storage and UI state
        clearSession();
        setSavedSessionData(null);
        setStage('framework-selection');
        setSelectedFramework(null);
        setInitialQuery('');
        setSessionId(null);
        setQueryId(null);
        setCurrentQuestion(null);
        setCurrentAspectId(null);
        setAspects([]);
        setSynthesis(null);
        setConversationHistory([]);
        setCommandResult(null);
        setError(null);

        console.log('[Refinement] State cleared, returning to framework selection');
    };

    const handleLogout = () => {
        clearSession();
        logout();
        navigate('/login');
    };

    return (
        <div className="refinement-page">
            <header className="refinement-header">
                <h1>MPH Dissertation Research Advisor</h1>
                <div className="header-actions">
                    {savedSessionData && stage === 'framework-selection' && (
                        <button onClick={handleResumeSession} className="btn-link btn-resume" disabled={loading}>
                            {loading ? 'Resuming...' : 'Resume Session'}
                        </button>
                    )}
                    {stage !== 'framework-selection' && (
                        <button onClick={handleStartOver} className="btn-link">
                            Start Over
                        </button>
                    )}
                    <button onClick={handleLogout} className="btn-link">
                        Logout
                    </button>
                </div>
            </header>

            <main className="refinement-content">
                {error && (
                    <div className="error-banner">
                        {error}
                        <button onClick={() => setError(null)}>×</button>
                    </div>
                )}

                {stage === 'framework-selection' && (
                    <>
                        {workflowLimitReached ? (
                            <div className="workflow-complete-notice">
                                <div className="notice-icon">✓</div>
                                <div className="notice-content">
                                    <h2>Thank You!</h2>
                                    <p>You have already completed one refinement workflow.</p>
                                    <p>For evaluation purposes, only one workflow per participant is allowed.</p>
                                    <p>Your contribution to the research study is greatly appreciated!</p>
                                </div>
                            </div>
                        ) : savedSessionData ? (
                            <div className="saved-session-notice">
                                <div className="notice-icon">💾</div>
                                <div className="notice-content">
                                    <h3>Continue Your Session?</h3>
                                    <p>
                                        You have an in-progress refinement session for the <strong>{savedSessionData.framework}</strong> framework.
                                    </p>
                                    <div className="notice-actions">
                                        <button
                                            onClick={handleResumeSession}
                                            className="btn-primary"
                                            disabled={loading}
                                        >
                                            {loading ? 'Resuming...' : 'Resume Session'}
                                        </button>
                                        <button
                                            onClick={handleStartOver}
                                            className="btn-secondary"
                                        >
                                            Start New Session
                                        </button>
                                    </div>
                                </div>
                            </div>
                        ) : (
                            <FrameworkSelector onSelect={handleFrameworkSelect} />
                        )}
                    </>
                )}

                {stage === 'initial-query' && (
                    <div className="initial-query-form">
                        <h2>Describe Your Research Dissertation Topic</h2>
                        <p>Framework: <strong>{selectedFramework}</strong></p>
                        <form onSubmit={handleInitialQuerySubmit}>
                            <textarea
                                value={initialQuery}
                                onChange={(e) => setInitialQuery(e.target.value)}
                                placeholder="Enter your dissertation topic, research idea, question, or statement..."
                                rows={6}
                                disabled={loading}
                            />
                            <div className="form-actions">
                                <button
                                    type="button"
                                    onClick={() => setStage('framework-selection')}
                                    className="btn-secondary"
                                >
                                    Back
                                </button>
                                <button
                                    type="submit"
                                    className="btn-primary"
                                    disabled={loading || !initialQuery.trim()}
                                >
                                    {loading ? 'Starting...' : 'Start Refinement'}
                                </button>
                            </div>
                        </form>
                    </div>
                )}

                {stage === 'refinement' && (
                    <div className="refinement-interface">
                        <div className="refinement-main">
                            {conversationHistory.length > 0 && (
                                <div className="history-panel">
                                    <div className="history-panel-header">Conversation History</div>
                                    <div className="conversation-history">
                                        {conversationHistory.map((item, index) => {
                                            if (item.type === 'command') {
                                                return (
                                                    <CommandHistoryItem
                                                        key={`${item.timestamp}-${index}`}
                                                        command={item.content}
                                                        result={item.result}
                                                    />
                                                );
                                            }
                                            return (
                                                <div key={`${item.timestamp}-${index}`} className={`history-item ${item.type}`}>
                                                    <div className="history-label">
                                                        {item.type === 'query' ? '📝 Initial Query' :
                                                            item.type === 'question' ? `❓ Question${item.aspectName ? ` (${item.aspectName})` : ''}` :
                                                                '💬 Your Answer'}
                                                    </div>
                                                    <div className="history-content">{item.content}</div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}

                            {currentQuestion && (
                                <div className="question-input-fixed">
                                    <QuestionRenderer
                                        question={currentQuestion.question || 'Please wait while we generate your question...'}
                                        aspectName={currentQuestion.name}
                                        aspectDescription={currentQuestion.description}
                                        onAnswer={handleAnswer}
                                        loading={loading}
                                    />
                                    <CommandButtons
                                        onCommand={handleCommand}
                                        disabled={loading}
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {stage === 'review' && (
                    <div className="refinement-interface">
                        <div className="refinement-main">
                            <div className="review-stage">
                                <div className="review-header">
                                    <h2>✓ All Dimensions Complete</h2>
                                    <p>Review your refined dimensions below. You can still use commands like <code>/back</code> or <code>/clear</code> to make changes.</p>
                                </div>

                                {conversationHistory.length > 0 && (
                                    <div className="history-panel">
                                        <div className="history-panel-header">Conversation History</div>
                                        <div className="conversation-history">
                                            {conversationHistory.map((item, index) => {
                                                if (item.type === 'command') {
                                                    return (
                                                        <CommandHistoryItem
                                                            key={`${item.timestamp}-${index}`}
                                                            command={item.content}
                                                            result={item.result}
                                                        />
                                                    );
                                                }
                                                return (
                                                    <div key={`${item.timestamp}-${index}`} className={`history-item ${item.type}`}>
                                                        <div className="history-label">
                                                            {item.type === 'query' ? '📝 Initial Query' :
                                                                item.type === 'question' ? `❓ Question${item.aspectName ? ` (${item.aspectName})` : ''}` :
                                                                    '💬 Your Answer'}
                                                        </div>
                                                        <div className="history-content">{item.content}</div>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </div>
                                )}

                                {aspects && aspects.length > 0 && (
                                    <div className="aspects-summary">
                                        <h3>Refined Dimensions Summary</h3>
                                        <div className="aspects-list">
                                            {aspects.map((aspect, index) => (
                                                <div key={index} className={`aspect-item ${aspect.is_complete ? 'complete' : 'incomplete'}`}>
                                                    <div className="aspect-name">
                                                        {aspect.is_complete ? '✓' : '○'} {aspect.aspect_name}
                                                    </div>
                                                    {aspect.normalized_value && (
                                                        <div className="aspect-value">{aspect.normalized_value}</div>
                                                    )}
                                                    {aspect.was_skipped && (
                                                        <div className="aspect-skipped">(Skipped)</div>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                <div className="review-actions">
                                    <button
                                        className="btn-primary btn-synthesis"
                                        onClick={async () => {
                                            logger.info('User manually triggered synthesis from review stage');
                                            setStage('synthesis');
                                            await handleSynthesis();
                                        }}
                                        disabled={loading}
                                    >
                                        {loading ? 'Generating...' : 'Generate Refined Query'}
                                    </button>
                                    <p className="review-hint">Or use commands to make changes: <code>/back</code>, <code>/clear [dimension]</code>, <code>/status</code></p>
                                </div>

                                <CommandButtons
                                    onCommand={handleCommand}
                                    disabled={loading}
                                />
                            </div>
                        </div>
                    </div>
                )}

                {stage === 'synthesis' && synthesis && (
                    <div className="refinement-interface">
                        <div className="refinement-main">
                            {/* Progress indicator during synthesis */}
                            {isPolling && progress && (
                                <ProgressIndicator progress={progress} />
                            )}

                            {conversationHistory.length > 0 && (
                                <div className="history-panel">
                                    <div className="history-panel-header">Conversation History</div>
                                    <div className="conversation-history">
                                        {conversationHistory.map((item, index) => {
                                            if (item.type === 'command') {
                                                return (
                                                    <CommandHistoryItem
                                                        key={`${item.timestamp}-${index}`}
                                                        command={item.content}
                                                        result={item.result}
                                                    />
                                                );
                                            }
                                            return (
                                                <div key={`${item.timestamp}-${index}`} className={`history-item ${item.type}`}>
                                                    <div className="history-label">
                                                        {item.type === 'query' ? '📝 Initial Query' :
                                                            item.type === 'question' ? `❓ Question${item.aspectName ? ` (${item.aspectName})` : ''}` :
                                                                '💬 Your Answer'}
                                                    </div>
                                                    <div className="history-content">{item.content}</div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}

                            <div className="question-input-fixed">
                                <SynthesisResult queryId={queryId} synthesis={synthesis} />
                            </div>
                        </div>
                    </div>
                )}
            </main>

            {/* Confirmation Dialog */}
            <ConfirmationDialog
                isOpen={confirmationDialog.isOpen}
                title={confirmationDialog.title}
                message={confirmationDialog.message}
                onConfirm={confirmationDialog.onConfirm}
                onCancel={() => setConfirmationDialog({ ...confirmationDialog, isOpen: false })}
                type={confirmationDialog.type}
                confirmText="Skip Dimension"
                cancelText="Cancel"
            />
        </div>
    );
};

export default Refinement;
