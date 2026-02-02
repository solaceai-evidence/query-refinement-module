import { useState } from 'react';
import './QuestionRenderer.css';

const QuestionRenderer = ({ question, onAnswer, loading, aspectName, aspectDescription }) => {
    const [answer, setAnswer] = useState('');

    const handleSubmit = (e) => {
        e.preventDefault();
        if (answer.trim()) {
            onAnswer(answer);
            setAnswer('');
        }
    };

    return (
        <div className={`question-renderer ${loading ? 'loading' : ''}`}>
            {loading && (
                <div className="loading-overlay">
                    <div className="loading-spinner"></div>
                    <div className="loading-text">Processing your answer...</div>
                </div>
            )}
            {aspectName && (
                <div className="dimension-badge">
                    <span className="dimension-icon">📋</span>
                    <span className="dimension-name">{aspectName}</span>
                    {aspectDescription && (
                        <span className="dimension-description" title={aspectDescription}>
                            <span className="info-icon">ℹ️</span>
                            <span className="description-text">{aspectDescription}</span>
                        </span>
                    )}
                </div>
            )}
            <div className="question-box">
                <div className="question-label">Question:</div>
                <div className="question-text">{question}</div>
            </div>

            <form onSubmit={handleSubmit} className="answer-form">
                <textarea
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    placeholder="Type your answer here..."
                    disabled={loading}
                    rows={4}
                />
                <button
                    type="submit"
                    className="btn-submit"
                    disabled={loading || !answer.trim()}
                >
                    {loading ? 'Processing...' : 'Submit Answer'}
                </button>
            </form>
        </div>
    );
};

export default QuestionRenderer;
