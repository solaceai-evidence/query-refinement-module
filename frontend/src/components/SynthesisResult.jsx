import { useState } from 'react';
import { refinementService } from '../services/refinement';
import './SynthesisResult.css';

const SynthesisResult = ({ queryId, synthesis }) => {
    const [rating, setRating] = useState(0);
    const [comment, setComment] = useState('');
    const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);

    const handleFeedbackSubmit = async (e) => {
        e.preventDefault();
        try {
            await refinementService.submitFeedback(queryId, rating, comment || null);
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
                <h3>Provide Feedback</h3>
                {feedbackSubmitted ? (
                    <div className="feedback-success">
                        Thank you for your feedback!
                    </div>
                ) : (
                    <form onSubmit={handleFeedbackSubmit} className="feedback-form">
                        <div className="rating-stars">
                            {[1, 2, 3, 4, 5].map((star) => (
                                <span
                                    key={star}
                                    className={`star ${rating >= star ? 'active' : ''}`}
                                    onClick={() => setRating(star)}
                                >
                                    ★
                                </span>
                            ))}
                        </div>
                        <textarea
                            value={comment}
                            onChange={(e) => setComment(e.target.value)}
                            placeholder="Optional: Share your thoughts about this refinement..."
                            rows={3}
                        />
                        <button
                            type="submit"
                            className="btn-submit"
                            disabled={rating === 0}
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
