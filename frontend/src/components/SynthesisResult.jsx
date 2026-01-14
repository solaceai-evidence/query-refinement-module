import { useState } from 'react';
import { refinementService } from '../services/refinement';
import './SynthesisResult.css';

const SynthesisResult = ({ queryId, synthesis }) => {
    const [comment, setComment] = useState('');
    const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);

    const handleFeedbackSubmit = async (e) => {
        e.preventDefault();
        try {
            // Send feedback without rating (research-focused comments only)
            await refinementService.submitFeedback(queryId, null, comment);
            setFeedbackSubmitted(true);
        } catch (error) {
            console.error('Failed to submit feedback:', error);
        }
    };

    const copyToClipboard = () => {
        navigator.clipboard.writeText(synthesis.refined_query);
    };

    const exportAsJson = () => {
        const data = JSON.stringify(synthesis, null, 2);
        const blob = new Blob([data], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `query-${queryId}.json`;
        a.click();
        URL.revokeObjectURL(url);
    };

    return (
        <div className="synthesis-result">
            <h2>✓ Refinement Complete</h2>

            <div className="result-section">
                <h3>Refined Query</h3>
                <div className="refined-query">
                    {synthesis.refined_query}
                </div>
                <div className="result-actions">
                    <button onClick={copyToClipboard} className="btn-secondary">
                        Copy to Clipboard
                    </button>
                    <button onClick={exportAsJson} className="btn-secondary">
                        Export as JSON
                    </button>
                </div>
            </div>

            {synthesis.metadata && (
                <div className="result-section">
                    <h3>Metadata</h3>
                    <div className="metadata">
                        {Object.entries(synthesis.metadata).map(([key, value]) => (
                            <div key={key} className="metadata-item">
                                <span className="metadata-key">{key}:</span>
                                <span className="metadata-value">{JSON.stringify(value)}</span>
                            </div>
                        ))}
                    </div>
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
