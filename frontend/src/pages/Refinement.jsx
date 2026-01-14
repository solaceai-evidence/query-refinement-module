import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import FrameworkSelector from '../components/FrameworkSelector';
import QuestionRenderer from '../components/QuestionRenderer';
import AspectStatusPanel from '../components/AspectStatusPanel';
import SynthesisResult from '../components/SynthesisResult';
import CommandButtons from '../components/CommandButtons';
import CommandHistoryItem from '../components/CommandHistoryItem';
import { refinementService } from '../services/refinement';
import { useAuth } from '../context/AuthContext';
import { isCommandResponse, createHistoryItem } from '../types';
import { isUserCommand } from '../constants/commands';
import { logger } from '../utils/logger';
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
    const { logout } = useAuth();
    const navigate = useNavigate();

    // Load session from localStorage on mount
    useEffect(() => {
        const savedSession = localStorage.getItem('refinement_session');
        if (savedSession) {
            try {
                const session = JSON.parse(savedSession);
                logger.info('Restoring session', { sessionId: session.sessionId, queryId: session.queryId });
                // Restore session state
                setSessionId(session.sessionId);
                setQueryId(session.queryId);
                setSelectedFramework(session.framework);
                setStage('refinement');
                // Could optionally reload query state from API
            } catch (e) {
                logger.error('Failed to restore session', e);
            }
        }
    }, []);

    // Save session to localStorage
    const saveSession = (sessionData) => {
        localStorage.setItem('refinement_session', JSON.stringify(sessionData));
    };

    const clearSession = () => {
        localStorage.removeItem('refinement_session');
    };

    const handleFrameworkSelect = (framework) => {
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

            logger.info('Refinement session started', {
                sessionId: response.session_id,
                queryId: response.query_id,
                aspectCount: response.summary?.aspects?.length || 0
            });

            setCurrentQuestion(response.next_prompt);
            setCurrentAspectId(response.next_prompt?.aspect_id);
            setAspects(response.summary?.aspects || []);
            setStage('refinement');

            // Save session
            const sessionData = {
                sessionId: response.session_id,
                queryId: response.query_id,
                framework: selectedFramework
            };
            saveSession(sessionData);

            // Add to conversation history
            setConversationHistory([{
                type: 'query',
                content: initialQuery
            }]);
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
            // Add answer or command to history
            setConversationHistory(prev => [...prev,
            createHistoryItem(isCommand ? 'command' : 'answer', answer, { aspectId: currentAspectId })
            ]);

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

                // Regular answer response - add question to history if next_prompt exists
                if (response.next_prompt) {
                    if (response.next_prompt.question) {
                        console.log('[TRACE] Adding next question to history');
                        setConversationHistory(prev => [...prev,
                        createHistoryItem('question', response.next_prompt.question, {
                            aspectId: response.next_prompt.aspect_id,
                            aspectName: response.next_prompt.aspect_name
                        })
                        ]);
                    } else {
                        console.warn('[TRACE] next_prompt.question is null or empty');
                    }
                    setCurrentQuestion(response.next_prompt);
                    setCurrentAspectId(response.next_prompt.aspect_id);
                } else {
                    console.log('[TRACE] No next_prompt - may trigger synthesis');
                    setCurrentQuestion(null);
                    setCurrentAspectId(null);
                    await handleSynthesis();
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
            console.error('Failed to update status:', err);
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
            setSynthesis(result);
            setStage('synthesis');
            clearSession(); // Clear saved session after completion
        } catch (err) {
            setError(err.response?.data?.detail || 'Failed to synthesize query');
        } finally {
            setLoading(false);
        }
    };

    const handleStartOver = () => {
        clearSession();
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
                    <FrameworkSelector onSelect={handleFrameworkSelect} />
                )}

                {stage === 'initial-query' && (
                    <div className="initial-query-form">
                        <h2>Enter Your Initial Query</h2>
                        <p>Framework: <strong>{selectedFramework}</strong></p>
                        <form onSubmit={handleInitialQuerySubmit}>
                            <textarea
                                value={initialQuery}
                                onChange={(e) => setInitialQuery(e.target.value)}
                                placeholder="Enter your research question or query..."
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
                        <div className="refinement-sidebar">
                            <AspectStatusPanel aspects={aspects} />
                        </div>
                        <div className="refinement-main">
                            <div className="conversation-container">
                                {conversationHistory.length > 0 && (
                                    <div className="conversation-history">
                                        {conversationHistory.map((item, index) => {
                                            if (item.type === 'command') {
                                                return (
                                                    <CommandHistoryItem
                                                        key={`${item.timestamp} -${index} `}
                                                        command={item.content}
                                                        result={item.result}
                                                    />
                                                );
                                            }
                                            return (
                                                <div key={`${item.timestamp} -${index} `} className={`history - item ${item.type} `}>
                                                    <div className="history-label">
                                                        {item.type === 'query' ? '📝 Initial Query' :
                                                            item.type === 'question' ? `❓ Question${item.aspectName ? ` (${item.aspectName})` : ''} ` :
                                                                '💬 Your Answer'}
                                                    </div>
                                                    <div className="history-content">{item.content}</div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                            {currentQuestion && currentQuestion.question && (
                                <div className="question-input-fixed">
                                    <QuestionRenderer
                                        question={currentQuestion.question}
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

                {stage === 'synthesis' && synthesis && (
                    <SynthesisResult queryId={queryId} synthesis={synthesis} />
                )}
            </main>
        </div>
    );
};

export default Refinement;
