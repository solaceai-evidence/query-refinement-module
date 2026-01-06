import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import FrameworkSelector from '../components/FrameworkSelector';
import QuestionRenderer from '../components/QuestionRenderer';
import AspectStatusPanel from '../components/AspectStatusPanel';
import SynthesisResult from '../components/SynthesisResult';
import { refinementService } from '../services/refinement';
import { useAuth } from '../context/AuthContext';
import './Refinement.css';

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
    const { logout } = useAuth();
    const navigate = useNavigate();

    // Load session from localStorage on mount
    useEffect(() => {
        const savedSession = localStorage.getItem('refinement_session');
        if (savedSession) {
            try {
                const session = JSON.parse(savedSession);
                // Restore session state
                setSessionId(session.sessionId);
                setQueryId(session.queryId);
                setSelectedFramework(session.framework);
                setStage('refinement');
                // Could optionally reload query state from API
            } catch (e) {
                console.error('Failed to restore session:', e);
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
            const response = await refinementService.startRefinement(
                selectedFramework,
                initialQuery
            );

            setSessionId(response.session_id);
            setQueryId(response.query_id);
            setCurrentQuestion(response.next_prompt);
            setCurrentAspectId(response.next_prompt?.aspect_id);
            setAspects(response.summary?.aspects || []);
            setStage('refinement');

            // Save session
            saveSession({
                sessionId: response.session_id,
                queryId: response.query_id,
                framework: selectedFramework
            });

            // Add to conversation history
            setConversationHistory([{
                type: 'query',
                content: initialQuery
            }]);
        } catch (err) {
            setError(err.response?.data?.detail || 'Failed to start refinement');
        } finally {
            setLoading(false);
        }
    };

    const handleAnswer = async (answer) => {
        setLoading(true);
        setError(null);

        try {
            // Add answer to history
            setConversationHistory(prev => [...prev, {
                type: 'answer',
                content: answer,
                aspectId: currentAspectId
            }]);

            const response = await refinementService.continueRefinement(
                sessionId,
                queryId,
                currentAspectId,
                answer
            );

            // Add question to history if next_prompt exists
            if (response.next_prompt) {
                setConversationHistory(prev => [...prev, {
                    type: 'question',
                    content: response.next_prompt,
                    aspectId: response.next_prompt.aspect_id
                }]);
                setCurrentQuestion(response.next_prompt);
                setCurrentAspectId(response.next_prompt.aspect_id);
            } else if (response.is_complete) {
                // Aspect complete, check if all aspects are done
                await handleSynthesis();
            }
        } catch (err) {
            setError(err.response?.data?.detail || 'Failed to process answer');
        } finally {
            setLoading(false);
        }
    };

    const handleSynthesis = async () => {
        setLoading(true);
        try {
            const response = await refinementService.getSynthesis(sessionId, queryId);
            setSynthesis(response);
            setStage('synthesis');
            clearSession();
        } catch (err) {
            setError(err.response?.data?.detail || 'Failed to generate synthesis');
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
                            {conversationHistory.length > 0 && (
                                <div className="conversation-history">
                                    {conversationHistory.map((item, index) => (
                                        <div key={index} className={`history-item ${item.type}`}>
                                            <div className="history-label">
                                                {item.type === 'query' ? 'Initial Query' :
                                                    item.type === 'question' ? 'Question' : 'Your Answer'}
                                            </div>
                                            <div className="history-content">{item.content}</div>
                                        </div>
                                    ))}
                                </div>
                            )}
                            {currentQuestion && (
                                <QuestionRenderer
                                    question={currentQuestion}
                                    onAnswer={handleAnswer}
                                    loading={loading}
                                />
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
