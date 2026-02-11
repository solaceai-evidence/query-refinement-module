import { useState } from 'react';
import { refinementService } from '../services/refinement';
import './SynthesisResult.css';

const Likert5 = ({ name, value, onChange, leftLabel = 'Strongly disagree', rightLabel = 'Strongly agree' }) => {
    return (
        <div className="likert">
            <div className="likert-labels">
                <span>{leftLabel}</span>
                <span>{rightLabel}</span>
            </div>
            <div className="likert-options" role="radiogroup" aria-label={name}>
                {[1, 2, 3, 4, 5].map((n) => (
                    <label key={n} className={`likert-option ${value === n ? 'selected' : ''}`}>
                        <input
                            type="radio"
                            name={name}
                            value={n}
                            checked={value === n}
                            onChange={() => onChange(n)}
                        />
                        <span>{n}</span>
                    </label>
                ))}
            </div>
        </div>
    );
};

const SynthesisResult = ({ queryId, synthesis }) => {
    const [rating, setRating] = useState(0);
    const [confidenceBefore, setConfidenceBefore] = useState(0);
    const [confidenceAfter, setConfidenceAfter] = useState(0);
    const [questionQuality, setQuestionQuality] = useState(0);
    const [easeOfUse, setEaseOfUse] = useState(0);
    const [feltInControl, setFeltInControl] = useState(0);
    const [timeSaved, setTimeSaved] = useState('');
    const [mostHelpful, setMostHelpful] = useState('');
    const [improvements, setImprovements] = useState('');
    const [otherComments, setOtherComments] = useState('');
    const [consentToUseData, setConsentToUseData] = useState(false);
    const [submitError, setSubmitError] = useState('');
    const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);

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

    const handleFeedbackSubmit = async (e) => {
        e.preventDefault();
        try {
            setSubmitError('');

            const metadata = {
                mph_survey_v1: {
                    time_saved: timeSaved || null,
                    confidence_before: confidenceBefore || null,
                    confidence_after: confidenceAfter || null,
                    question_quality: questionQuality || null,
                    ease_of_use: easeOfUse || null,
                    felt_in_control: feltInControl || null,
                },
                free_text: {
                    most_helpful: mostHelpful.trim() || null,
                    improvements: improvements.trim() || null,
                    other: otherComments.trim() || null,
                },
                ui_context: {
                    query_id: queryId,
                }
            };

            const comments = [
                `Most helpful: ${mostHelpful.trim()}`,
                `Improvements: ${improvements.trim()}`,
                otherComments.trim() ? `Other: ${otherComments.trim()}` : null,
            ].filter(Boolean).join('\n');

            await refinementService.submitFeedback(queryId, rating || null, comments, metadata, consentToUseData);
            setFeedbackSubmitted(true);
        } catch (error) {
            console.error('Failed to submit feedback:', error);
            setSubmitError(error?.response?.data?.detail || 'Failed to submit feedback. Please try again.');
        }
    };

    const isLikertValid = (value) => Number.isInteger(value) && value >= 1 && value <= 5;
    const canSubmit =
        isLikertValid(rating) &&
        isLikertValid(confidenceBefore) &&
        isLikertValid(confidenceAfter) &&
        isLikertValid(questionQuality) &&
        isLikertValid(easeOfUse) &&
        isLikertValid(feltInControl) &&
        mostHelpful.trim().length > 0 &&
        improvements.trim().length > 0;

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

    return (
        <div className="synthesis-result">
            <h2>✓ Refinement Complete</h2>

            <div className="result-section">
                <h3>Integrated Statement</h3>
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
            </div>

            <div className="result-section">
                <h3>Share Your Experience</h3>
                <p className="feedback-intro">
                    This short survey is part of the MPH student workflow. Your responses help improve the tool and support research on AI-assisted dissertation planning.
                </p>
                {feedbackSubmitted ? (
                    <div className="feedback-success">
                        Thank you for your feedback! Your input is valuable for our research.
                    </div>
                ) : (
                    <form onSubmit={handleFeedbackSubmit} className="feedback-form">
                        <div className="feedback-questions">
                            <p className="feedback-prompt">Quick ratings (1–5)</p>

                            <div className="feedback-field">
                                <div className="feedback-field-title">Overall, I would rate this tool as helpful for clarifying my dissertation topic.</div>
                                <Likert5 name="overall_helpful" value={rating} onChange={setRating} />
                            </div>

                            <div className="feedback-field">
                                <div className="feedback-field-title">Before using the tool, I felt confident about the clarity/specificity of my topic.</div>
                                <Likert5 name="confidence_before" value={confidenceBefore} onChange={setConfidenceBefore} />
                            </div>

                            <div className="feedback-field">
                                <div className="feedback-field-title">After using the tool, I feel confident about the clarity/specificity of my topic.</div>
                                <Likert5 name="confidence_after" value={confidenceAfter} onChange={setConfidenceAfter} />
                            </div>

                            <div className="feedback-field">
                                <div className="feedback-field-title">The questions asked by the chatbot were relevant and improved my thinking.</div>
                                <Likert5 name="question_quality" value={questionQuality} onChange={setQuestionQuality} />
                            </div>

                            <div className="feedback-field">
                                <div className="feedback-field-title">The tool was easy to use.</div>
                                <Likert5 name="ease_of_use" value={easeOfUse} onChange={setEaseOfUse} leftLabel="Very difficult" rightLabel="Very easy" />
                            </div>

                            <div className="feedback-field">
                                <div className="feedback-field-title">I felt in control of the refinement process (e.g., could revise/skip/finish when needed).</div>
                                <Likert5 name="felt_in_control" value={feltInControl} onChange={setFeltInControl} />
                            </div>

                            <div className="feedback-field">
                                <label className="feedback-field-title" htmlFor="timeSaved">How much time did this tool save you overall?</label>
                                <select
                                    id="timeSaved"
                                    className="feedback-select"
                                    value={timeSaved}
                                    onChange={(e) => setTimeSaved(e.target.value)}
                                >
                                    <option value="">Select an option</option>
                                    <option value="none">No time saved</option>
                                    <option value="a_little">A little</option>
                                    <option value="some">Some</option>
                                    <option value="a_lot">A lot</option>
                                </select>
                            </div>
                        </div>

                        <div className="feedback-field">
                            <label className="feedback-field-title" htmlFor="mostHelpful">What was the most helpful part of the experience? (required)</label>
                            <textarea
                                id="mostHelpful"
                                value={mostHelpful}
                                onChange={(e) => setMostHelpful(e.target.value)}
                                rows={4}
                                required
                            />
                        </div>

                        <div className="feedback-field">
                            <label className="feedback-field-title" htmlFor="improvements">What should we improve? (required)</label>
                            <textarea
                                id="improvements"
                                value={improvements}
                                onChange={(e) => setImprovements(e.target.value)}
                                rows={4}
                                required
                            />
                        </div>

                        <div className="feedback-field">
                            <label className="feedback-field-title" htmlFor="otherComments">Anything else you’d like to add? (optional)</label>
                            <textarea
                                id="otherComments"
                                value={otherComments}
                                onChange={(e) => setOtherComments(e.target.value)}
                                rows={3}
                            />
                        </div>

                        <div className="feedback-consent">
                            <label className="feedback-consent-row">
                                <input
                                    type="checkbox"
                                    checked={consentToUseData}
                                    onChange={(e) => setConsentToUseData(e.target.checked)}
                                />
                                <span>
                                    I consent for my query session data and this feedback to be retained and used for research/analysis.
                                </span>
                            </label>
                            <div className="feedback-consent-note">
                                If you do not consent, your feedback can still be submitted, but the study team may delete your session data.
                            </div>
                        </div>

                        {submitError ? <div className="feedback-error">{submitError}</div> : null}

                        <button
                            type="submit"
                            className="btn-submit"
                            disabled={!canSubmit}
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
