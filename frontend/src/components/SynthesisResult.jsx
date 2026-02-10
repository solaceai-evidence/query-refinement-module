import { useState } from 'react';
import { refinementService } from '../services/refinement';
import './SynthesisResult.css';

const SynthesisResult = ({ queryId, synthesis }) => {
    const [comment, setComment] = useState('');
    const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
    const [expandedSections, setExpandedSections] = useState({
        refinedQuery: true,
        structuredOutput: true,
        metadata: false
    });

    // Debug logging
    console.log('[SynthesisResult] Component rendered');
    console.log('[SynthesisResult] Props:', { queryId, synthesis });
    console.log('[SynthesisResult] synthesis type:', typeof synthesis);
    console.log('[SynthesisResult] synthesis keys:', synthesis ? Object.keys(synthesis) : 'null');
    console.log('[SynthesisResult] integrated_statement:', synthesis?.integrated_statement);
    console.log('[SynthesisResult] integrated_statement type:', typeof synthesis?.integrated_statement);

    // Safety check for synthesis object
    if (!synthesis || typeof synthesis !== 'object') {
        console.error('[SynthesisResult] Invalid synthesis object:', synthesis);
        console.error('[SynthesisResult] Expected object, got:', typeof synthesis);
        return (
            <div className="synthesis-result">
                <div className="error-banner">
                    <p>⚠️ Synthesis result is invalid. Please try again.</p>
                    <p style={{ fontSize: '0.9em', marginTop: '8px' }}>Debug: Received {typeof synthesis}</p>
                </div>
            </div>
        );
    }

    // Check if integrated_statement exists
    if (!synthesis.integrated_statement) {
        console.error('[SynthesisResult] Missing integrated_statement field');
        console.error('[SynthesisResult] Available fields:', Object.keys(synthesis));
        return (
            <div className="synthesis-result">
                <div className="error-banner">
                    <p>⚠️ Synthesis result is incomplete - missing integrated statement.</p>
                    <p style={{ fontSize: '0.9em', marginTop: '8px' }}>Debug: Missing integrated_statement field</p>
                </div>
            </div>
        );
    }

    // Use integrated_statement directly - API now properly parses and extracts it
    const integratedStatement = synthesis.integrated_statement;

    // Safety check: if integrated_statement somehow contains raw JSON (should not happen anymore)
    if (typeof integratedStatement === 'string' && integratedStatement.startsWith('{')) {
        console.warn('[SynthesisResult] ⚠️ integrated_statement appears to be raw JSON - this indicates an API parsing issue');
        console.error('[SynthesisResult] Raw JSON in integrated_statement:', integratedStatement.substring(0, 200));
    }

    const toggleSection = (section) => {
        setExpandedSections(prev => ({
            ...prev,
            [section]: !prev[section]
        }));
    };

    const handleFeedbackSubmit = async (e) => {
        e.preventDefault();
        try {
            await refinementService.submitFeedback(queryId, null, comment);
            setFeedbackSubmitted(true);
        } catch (error) {
            console.error('Failed to submit feedback:', error);
        }
    };

    const copyToClipboard = (text, label = 'text') => {
        navigator.clipboard.writeText(text);
        // Could add toast notification here
        console.log(`Copied ${label} to clipboard`);
    };

    const exportAsJson = () => {
        const data = JSON.stringify(synthesis, null, 2);
        const blob = new Blob([data], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `query-refinement-${queryId}.json`;
        a.click();
        URL.revokeObjectURL(url);
    };

    // Render structured data in a readable format
    const renderStructuredData = (data, depth = 0) => {
        if (data === null || data === undefined) {
            return <span className="json-null">null</span>;
        }

        if (typeof data === 'boolean') {
            return <span className="json-boolean">{data.toString()}</span>;
        }

        if (typeof data === 'number') {
            return <span className="json-number">{data}</span>;
        }

        if (typeof data === 'string') {
            return <span className="json-string">"{data}"</span>;
        }

        if (Array.isArray(data)) {
            if (data.length === 0) return <span className="json-empty">[]</span>;

            return (
                <div className="json-array" style={{ marginLeft: `${depth * 20}px` }}>
                    {data.map((item, index) => (
                        <div key={index} className="json-array-item">
                            <span className="json-index">[{index}]</span>
                            {renderStructuredData(item, depth + 1)}
                        </div>
                    ))}
                </div>
            );
        }

        if (typeof data === 'object') {
            const entries = Object.entries(data);
            if (entries.length === 0) return <span className="json-empty">{'{}'}</span>;

            return (
                <div className="json-object" style={{ marginLeft: `${depth * 20}px` }}>
                    {entries.map(([key, value]) => (
                        <div key={key} className="json-property">
                            <span className="json-key">{key}:</span>
                            {renderStructuredData(value, depth + 1)}
                        </div>
                    ))}
                </div>
            );
        }

        return <span>{String(data)}</span>;
    };

    return (
        <div className="synthesis-result">
            <h2>✓ Refinement Complete</h2>

            <div className="result-section">
                <div className="section-header" onClick={() => toggleSection('refinedQuery')}>
                    <h3>Integrated Statement</h3>
                    <span className="toggle-icon">{expandedSections.refinedQuery ? '−' : '+'}</span>
                </div>
                {expandedSections.refinedQuery && (
                    <>
                        <div className="refined-query">
                            {integratedStatement || '(No integrated statement available)'}
                        </div>
                        <div className="result-actions">
                            <button
                                onClick={() => copyToClipboard(integratedStatement, 'integrated statement')}
                                className="btn-secondary"
                                disabled={!integratedStatement}
                            >
                                📋 Copy Statement
                            </button>
                            <button onClick={exportAsJson} className="btn-secondary">
                                💾 Export JSON
                            </button>
                        </div>
                    </>
                )}
            </div>

            {synthesis.structured_output && (
                <div className="result-section">
                    <div className="section-header" onClick={() => toggleSection('structuredOutput')}>
                        <h3>Structured Research Output</h3>
                        <span className="toggle-icon">{expandedSections.structuredOutput ? '−' : '+'}</span>
                    </div>
                    {expandedSections.structuredOutput && (
                        <>
                            <div className="structured-output">
                                {renderStructuredData(synthesis.structured_output)}
                            </div>
                            <div className="result-actions">
                                <button
                                    onClick={() => copyToClipboard(JSON.stringify(synthesis.structured_output, null, 2), 'structured output')}
                                    className="btn-secondary"
                                >
                                    📋 Copy JSON
                                </button>
                            </div>
                        </>
                    )}
                </div>
            )}

            {synthesis.metadata && Object.keys(synthesis.metadata).length > 0 && (
                <div className="result-section">
                    <div className="section-header" onClick={() => toggleSection('metadata')}>
                        <h3>Metadata</h3>
                        <span className="toggle-icon">{expandedSections.metadata ? '−' : '+'}</span>
                    </div>
                    {expandedSections.metadata && (
                        <div className="metadata">
                            {renderStructuredData(synthesis.metadata)}
                        </div>
                    )}
                </div>
            )}

            <div className="result-section">
                <h3>Share Your Experience</h3>
                <p className="feedback-intro">
                    Your feedback helps us improve this tool and contributes to research on AI-assisted dissertation planning.
                </p>
                {feedbackSubmitted ? (
                    <div className="feedback-success">
                        Thank you for your feedback! Your input is valuable for our research.
                    </div>
                ) : (
                    <form onSubmit={handleFeedbackSubmit} className="feedback-form">
                        <div className="feedback-questions">
                            <p className="feedback-prompt">Please reflect on your experience:</p>
                            <ul className="feedback-guide">
                                <li><strong>Time efficiency:</strong> How much time did this tool save compared to manually reviewing literature or brainstorming alone?</li>
                                <li><strong>Confidence level:</strong> How confident were you in your research topic before and after using this tool?</li>
                                <li><strong>Question quality:</strong> How would you rate the quality and relevance of the questions the chatbot asked?</li>
                                <li><strong>Limitations:</strong> In what areas did the chatbot fall short or fail to meet your expectations?</li>
                                <li><strong>Ease of use:</strong> How easy or difficult was it to use this tool?</li>
                            </ul>
                        </div>
                        <textarea
                            value={comment}
                            onChange={(e) => setComment(e.target.value)}
                            placeholder="Please address the questions above in your feedback. Be as specific as possible - your insights will help improve this tool and contribute to research on AI-assisted dissertation planning."
                            rows={8}
                            required
                        />
                        <button
                            type="submit"
                            className="btn-submit"
                            disabled={!comment.trim()}
                        >
                            Submit Feedback
                        </button>
                    </form>
                )}
            </div>
        </div>
    );
};

export default SynthesisResult;
