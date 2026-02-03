import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import FrameworkSelector from '../components/FrameworkSelector';
import QuestionRenderer from '../components/QuestionRenderer';
import SynthesisResult from '../components/SynthesisResult';
import CommandButtons from '../components/CommandButtons';
import CommandHistoryItem from '../components/CommandHistoryItem';
import ConfirmationDialog from '../components/ConfirmationDialog';
import { refinementService } from '../services/refinement';
import { useAuth } from '../context/AuthContext';
import { isCommandResponse, createHistoryItem } from '../types';
import { isUserCommand } from '../constants/commands';
import { logger } from '../utils/logger';
import { setLogSessionId, logUserAction } from '../utils/logForwarder';
import './Refinement.css';

/**
 * @typedef {import('../types/api').NextPrompt} NextPrompt
 * @typedef {import('../types/api').ConversationHistoryItem} ConversationHistoryItem
 * @typedef {import('../types/api').CommandResult} CommandResult
 * @typedef {import('../types/api').AspectSummary} AspectSummary
 * @typedef {import('../types/api').SynthesizeQueryResponse} SynthesizeQueryResponse
 */

const Refinement = () => {
    const [stage, setStage] = useState('framework-selection'); // framework-selection, initial-query, refinement, synthesis
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
    const [confirmationDialog, setConfirmationDialog] = useState({
        isOpen: false,
        title: '',
        message: '',
        onConfirm: null,
        type: 'warning'
    });
    const { logout } = useAuth();
    const navigate = useNavigate();

    // Check for saved session but don't auto-restore
    const [savedSessionData, setSavedSessionData] = useState(null);
    const [userStatus, setUserStatus] = useState(null);
    const [workflowLimitReached, setWorkflowLimitReached] = useState(false);

    useEffect(() => {
        const savedSession = localStorage.getItem('refinement_session');
        if (savedSession) {
            try {
                const session = JSON.parse(savedSession);
                logger.info('Found saved session', { sessionId: session.sessionId, queryId: session.queryId });
                setSavedSessionData(session);
            } catch (e) {
                logger.error('Failed to parse saved session', e);
                localStorage.removeItem('refinement_session');
            }
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

    // Save session to localStorage
    const saveSession = (sessionData) => {
        localStorage.setItem('refinement_session', JSON.stringify(sessionData));
    };

    const clearSession = () => {
        localStorage.removeItem('refinement_session');
    };

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
                    aspectName: response.next_prompt.aspect_name
                });
            }

            setCurrentQuestion(response.next_prompt);
            setCurrentAspectId(response.next_prompt?.aspect_id);
            setAspects(response.summary?.aspects || []);

            // Check if all aspects are immediately complete (ready for synthesis)
            if (response.ready_for_synthesis && !response.next_prompt) {
                logger.info('All aspects complete immediately - triggering synthesis');
                setStage('synthesis');
                await handleSynthesis();
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
                    aspectName: response.next_prompt.aspect_name,
                    timestamp: new Date().toISOString()
                }] : [])
            ]);
        } catch (err) {
            logger.error('Failed to start refinement', err, { framework: selectedFramework });
            setError(err.response?.data?.detail || 'Failed to start refinement');
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

            // Check if this is a command response using type guard
            if (isCommandResponse(response)) {
                logger.info('Command executed', {
                    commandType: response.command_type,
                    success: response.success,
                    hasNextPrompt: !!response.next_prompt
                });

                /** @type {CommandResult} */
                const commandResultData = {
                    type: response.command_type,
                    message: response.message,
                    success: response.success,
                    step_summary: response.step_summary,
                    step_list: response.step_list,
                    invalidated_aspects: response.invalidated_aspects
                };

                console.log('[COMMAND RESPONSE] Setting command result:', commandResultData);

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
                                aspectName: response.next_prompt.aspect_name
                            })
                            ]);
                        } else {
                            console.log('[COMMAND RESPONSE] Same question - not adding to history');
                        }

                        console.log('[COMMAND RESPONSE] Updating current question state');
                        setCurrentQuestion(response.next_prompt);
                        setCurrentAspectId(response.next_prompt.aspect_id);
                    } else {
                        // next_prompt exists but question is null - preserve current state
                        console.log('[COMMAND RESPONSE] next_prompt.question is null - preserving current state');
                        // Don't update currentQuestion or currentAspectId
                    }
                } else {
                    // No next_prompt in response - check command behavior
                    const { isInformationalCommand } = await import('../constants/commands');
                    const isInfoCommand = isInformationalCommand(answer);

                    if (isInfoCommand) {
                        // Informational commands don't change flow state - keep current question
                        console.log('[COMMAND RESPONSE] Informational command - preserving current question');
                        // currentQuestion and currentAspectId remain unchanged
                    } else {
                        // Navigation/control commands without next_prompt trigger synthesis
                        console.log('[COMMAND RESPONSE] No next_prompt - may trigger synthesis');
                        setCurrentQuestion(null);
                        setCurrentAspectId(null);
                        await handleSynthesis();
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
                            aspectName: response.next_prompt.aspect_name
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
                            aspectName: response.next_prompt.aspect_name
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
                        logger.info('All aspects complete - triggering synthesis');
                        await handleSynthesis();
                    }
                }

                // Fetch updated status to refresh aspects
                await updateAspectStatus();
            }
        } catch (err) {
            console.error('[ERROR] Error in handleAnswer:', err);
            console.error('[ERROR] Error response:', err.response?.data);
            setError(err.response?.data?.detail || err.message || 'Failed to process answer');
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

        // Special handling for /skip command - confirm if there's existing data
        if (command.trim() === '/skip') {
            // Check if there are any answers for the current dimension in history
            const currentDimensionAnswers = conversationHistory.filter(
                item => item.type === 'answer' && item.aspectId === currentAspectId
            );

            if (currentDimensionAnswers.length > 0) {
                // Dimension has answers - show confirmation dialog
                const dimensionName = currentQuestion?.aspect_name || 'this dimension';

                setConfirmationDialog({
                    isOpen: true,
                    title: 'Skip Dimension?',
                    message: `Skipping "${dimensionName}" will remove all ${currentDimensionAnswers.length} answer(s) you've already provided for this dimension.\n\nDo you want to continue?`,
                    type: 'warning',
                    onConfirm: async () => {
                        console.log('[COMMAND HANDLER] Skip confirmed by user');
                        setConfirmationDialog({ ...confirmationDialog, isOpen: false });
                        await handleAnswer(command);
                    }
                });
                return; // Wait for user confirmation
            }
        }

        // Commands are handled through handleAnswer
        await handleAnswer(command);
    };

    /**
     * Request synthesis of refined query
     * @returns {Promise<void>}
     */
    const handleSynthesis = async () => {
        if (!queryId || !sessionId) return;

        setLoading(true);
        try {
            const result = await refinementService.getSynthesis(queryId);
            console.log('Synthesis result received:', result);
            console.log('Synthesis refined_query:', result?.refined_query);
            console.log('Synthesis structured_output:', result?.structured_output);

            // Validate result before setting state
            if (!result || typeof result !== 'object') {
                throw new Error('Invalid synthesis response format');
            }

            // Check for truncated JSON in refined_query
            if (result.refined_query &&
                typeof result.refined_query === 'string' &&
                (result.refined_query.includes('```json') || result.refined_query.startsWith('{'))) {
                console.warn('⚠️ Synthesis returned raw JSON instead of parsed result');

                // Try to extract synthesized_statement from the JSON string
                try {
                    // Remove markdown fences
                    let jsonStr = result.refined_query.replace(/```json\n?/g, '').replace(/```\n?$/g, '');

                    // Check if truncated
                    if (!jsonStr.trim().endsWith('}')) {
                        console.error('❌ JSON response is truncated!');
                        setError('The synthesis response was incomplete. This usually means the LLM response was too long. Please try again or contact support.');
                        return;
                    }

                    const parsed = JSON.parse(jsonStr);
                    if (parsed.synthesized_statement) {
                        result.refined_query = parsed.synthesized_statement;
                        result.structured_output = parsed;
                        console.log('✓ Successfully extracted synthesized_statement:', result.refined_query.substring(0, 100));
                    }
                } catch (parseErr) {
                    console.error('Failed to parse JSON from refined_query:', parseErr);
                    setError('The synthesis response could not be processed. Please try again.');
                    return;
                }
            }

            setSynthesis(result);
            setStage('synthesis');
            clearSession(); // Clear saved session after completion
        } catch (err) {
            console.error('Synthesis error:', err);
            console.error('Error response:', err.response?.data);
            setError(err.response?.data?.detail || err.message || 'Failed to synthesize query');
        } finally {
            setLoading(false);
        }
    };

    const handleResumeSession = async () => {
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

            logger.info('Session resumed', {
                sessionId: savedSessionData.sessionId,
                queryId: savedSessionData.queryId,
                stage: status.ready_for_synthesis ? 'synthesis' : 'refinement'
            });

            // Set aspects
            setAspects(status.aspects || []);

            // Check if ready for synthesis
            if (status.ready_for_synthesis && !status.next_prompt) {
                setStage('synthesis');
                await handleSynthesis();
            } else {
                setCurrentQuestion(status.next_prompt);
                setCurrentAspectId(status.next_prompt?.aspect_id);
                setStage('refinement');
            }

            // Clear the saved session notification
            setSavedSessionData(null);
        } catch (err) {
            logger.error('Failed to resume session', err);
            setError('Failed to resume session. Please start a new one.');
            clearSession();
            setSavedSessionData(null);
        } finally {
            setLoading(false);
        }
    };

    const handleStartOver = () => {
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
                                        aspectName={currentQuestion.aspect_name}
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

                        {stage === 'synthesis' && synthesis && (
                            <SynthesisResult queryId={queryId} synthesis={synthesis} />
                        )}
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
