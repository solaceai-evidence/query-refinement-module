import { useMemo, useState } from 'react';
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

const SynthesisResult = ({ queryId, synthesis, selectedFramework = null, aspects = [] }) => {
    const [rating, setRating] = useState(0);
    const [confidenceBefore, setConfidenceBefore] = useState(0);
    const [confidenceAfter, setConfidenceAfter] = useState(0);
    const [questionQuality, setQuestionQuality] = useState(0);
    const [newParametersPrompting, setNewParametersPrompting] = useState(0);
    const [easeOfUse, setEaseOfUse] = useState(0);
    const [feltInControl, setFeltInControl] = useState(0);
    const [toneSelection, setToneSelection] = useState('');
    const [complexitySelection, setComplexitySelection] = useState('');
    const [timeSaved, setTimeSaved] = useState('');
    const [mostHelpful, setMostHelpful] = useState('');
    const [improvements, setImprovements] = useState('');
    const [otherComments, setOtherComments] = useState('');
    const [consentSelection, setConsentSelection] = useState('');
    const [submitError, setSubmitError] = useState('');
    const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
    const [submitting, setSubmitting] = useState(false);

    const toneOptions = useMemo(() => ([
        {
            value: 'educational',
            label: 'Educational',
            description: 'Encouraging, explains the rationale, and uses examples.'
        },
        {
            value: 'professional',
            label: 'Professional',
            description: 'Direct, concise, and focused on clear specifications.'
        },
        {
            value: 'pragmatic',
            label: 'Pragmatic',
            description: 'Practical, feasibility-focused, and action oriented.'
        }
    ]), []);

    const complexityOptions = useMemo(() => ([
        {
            value: 'novice',
            label: 'Novice',
            description: 'Defines terms, keeps explanations simple, and checks understanding.'
        },
        {
            value: 'intermediate',
            label: 'Intermediate',
            description: 'Uses standard research terms with brief context when needed.'
        },
        {
            value: 'advanced',
            label: 'Advanced',
            description: 'Uses technical language and discusses tradeoffs.'
        },
        {
            value: 'expert',
            label: 'Expert',
            description: 'Peer-level language with critical, methodological pushback.'
        }
    ]), []);

    const frameworkConstraintStrings = useMemo(() => ({
        pico_advanced: [
            'Specificity check: Every dimension must have concrete, measurable definitions without ambiguous terms (reject \'elderly\', \'standard care\', \'improved outcomes\' unless operationalized)',
            'Alignment check: All dimensions must be mutually compatible (intervention appropriate for population and condition, outcome measurable given design constraints)',
            'Search-readiness check: Each element can be converted into specific database search terms, MeSH headings, or screening criteria',
            'Completeness check: All critical PICO elements defined without circular dependencies (no \'depends on what studies we find\')',
            'Synthesis-feasibility check: The combined dimensions define a coherent, comparable body of evidence rather than heterogeneous narrative-only collection',
        ],
        mph_dissertation: [
            'Timeline: 6-12 months limits study designs (prospective cohorts, RCTs, and longitudinal designs infeasible; cross-sectional, retrospective, or rapid reviews preferred)',
            'Ethics approval: Primary data collection requires ethics committee approval (2-3 months expedited, 4-6 months full review); NHS ethics for patient data adds further complexity',
            'Sample size: Primary data collection >200 (surveys) or >100 (in-person) or >30 (clinical) typically exceeds capacity; secondary data (UK Data Service, ONS, CPRD) or smaller qualitative samples (15-25) preferred',
            'Scope and methods: Single focused research question; mixed methods with equal weighting or novel instrument development rarely feasible within timeframe',
            'Data access: UK datasets requiring application (CPRD, HES, longitudinal cohorts) take 1-3 months approval; publicly available datasets (Health Survey for England, Understanding Society) or institutional data preferred',
            'Resources: Projects requiring substantial budget (participant incentives, professional transcription, proprietary software, travel) may need funding applications; low-cost or unfunded approaches preferred',
        ],
        legal_research: [
            'Jurisdiction: Must specify applicable legal jurisdiction (federal vs state, specific circuit)',
            'Precedent research: Need manageable scope for case law review within academic timeline',
            'Legal standards: Must identify controlling statutes, regulations, or common law doctrines',
            'Time period: Consider whether historical or contemporary legal framework applies',
        ],
    }), []);

    const normalizedFrameworkKey = useMemo(() => {
        if (!selectedFramework) return null;
        return selectedFramework
            .toLowerCase()
            .replace(/[\s-]+/g, '_')
            .replace(/[^a-z0-9_]/g, '');
    }, [selectedFramework]);

    const surveyConfig = useMemo(() => {
        const configs = {
            pico_advanced: {
                intro: 'This short survey is for systematic reviewers using the PICO refinement framework. Your responses help improve the tool and support research on AI-assisted evidence synthesis.',
                overall_helpful: 'Overall, I would rate this tool as helpful for structuring my systematic review question.',
                confidence_before: 'Before using the tool, I felt confident about the precision of my PICO question.',
                confidence_after: 'After using the tool, I feel confident about the precision of my PICO question.',
                question_quality: 'The questions asked by the chatbot were relevant and helped sharpen my PICO elements.',
                new_parameters_prompting: 'To what extent did the chatbot prompt you to consider PICO elements you had not previously defined?',
                ease_of_use: 'The tool was easy to use.',
                felt_in_control: 'I felt in control of the refinement process (e.g., could revise/skip/finish when needed).',
            },
            mph_dissertation: {
                intro: 'This short survey is part of the MPH student workflow. Your responses help improve the tool and support research on AI-assisted dissertation planning.',
                overall_helpful: 'Overall, I would rate this tool as helpful for clarifying my dissertation topic.',
                confidence_before: 'Before using the tool, I felt confident about the clarity/specificity of my dissertation topic.',
                confidence_after: 'After using the tool, I feel confident about the clarity/specificity of my dissertation topic.',
                question_quality: 'The questions asked by the chatbot were relevant and improved my thinking about my dissertation.',
                new_parameters_prompting: 'To what extent did the chatbot prompt you to consider new parameters for your research question?',
                ease_of_use: 'The tool was easy to use.',
                felt_in_control: 'I felt in control of the refinement process (e.g., could revise/skip/finish when needed).',
            },
        };
        return configs[normalizedFrameworkKey] || {
            intro: 'This short survey helps us improve the tool. Your responses support research on AI-assisted research question refinement.',
            overall_helpful: 'Overall, I would rate this tool as helpful for clarifying my research question.',
            confidence_before: 'Before using the tool, I felt confident about the clarity and specificity of my research question.',
            confidence_after: 'After using the tool, I feel confident about the clarity and specificity of my research question.',
            question_quality: 'The questions asked by the chatbot were relevant and improved my thinking.',
            new_parameters_prompting: 'To what extent did the chatbot prompt you to consider new parameters for your research question?',
            ease_of_use: 'The tool was easy to use.',
            felt_in_control: 'I felt in control of the refinement process (e.g., could revise/skip/finish when needed).',
        };
    }, [normalizedFrameworkKey]);

    const surveyMetaKey = normalizedFrameworkKey ? `${normalizedFrameworkKey}_survey_v1` : 'mph_survey_v1';

    const constraints = useMemo(() => {
        const rawList = frameworkConstraintStrings[normalizedFrameworkKey] || [];
        const audienceByFramework = {
            pico_advanced: 'Systematic reviewers',
            mph_dissertation: 'MPH students',
        };
        const audience = audienceByFramework[normalizedFrameworkKey] || '';

        return rawList.map((text, index) => {
            const [labelPart, ...rest] = text.split(':');
            const label = labelPart?.trim() || `Constraint ${index + 1}`;
            const description = rest.join(':').trim() || text;
            const id = label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
            return { id: id || `constraint_${index + 1}`, label, description, audience };
        });
    }, [frameworkConstraintStrings, normalizedFrameworkKey]);

    const dimensionOptions = useMemo(() => {
        const labels = (aspects || [])
            .map((aspect) => aspect?.aspect_name || aspect?.name || aspect?.aspect_id || aspect?.id || null)
            .filter(Boolean);
        return Array.from(new Set(labels));
    }, [aspects]);

    const [constraintResponses, setConstraintResponses] = useState(() =>
        constraints.map(() => ({ considered: '', dimensions: [] }))
    );

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
        if (submitting || feedbackSubmitted) return; // Guard against double-submit
        setSubmitting(true);
        try {
            setSubmitError('');

            const consentToUseData = consentSelection === 'yes';

            const metadata = {
                [surveyMetaKey]: {
                    time_saved: timeSaved || null,
                    confidence_before: confidenceBefore || null,
                    confidence_after: confidenceAfter || null,
                    question_quality: questionQuality || null,
                    new_parameters_prompting: newParametersPrompting || null,
                    ease_of_use: easeOfUse || null,
                    felt_in_control: feltInControl || null,
                    tone_selected: toneSelection || null,
                    complexity_selected: complexitySelection || null,
                },
                constraint_feedback: {
                    framework: selectedFramework || null,
                    framework_key: normalizedFrameworkKey,
                    constraints: constraints.map((constraint, index) => ({
                        id: constraint.id,
                        label: constraint.label,
                        considered: constraintResponses[index]?.considered || null,
                        dimensions: constraintResponses[index]?.dimensions || [],
                    })),
                },
                consent: {
                    selection: consentSelection || null,
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
                mostHelpful.trim() ? `Most helpful: ${mostHelpful.trim()}` : null,
                improvements.trim() ? `Improvements: ${improvements.trim()}` : null,
                otherComments.trim() ? `Other: ${otherComments.trim()}` : null,
            ].filter(Boolean).join('\n');

            await refinementService.submitFeedback(queryId, rating || null, comments || null, metadata, consentToUseData);
            setFeedbackSubmitted(true);
        } catch (error) {
            console.error('Failed to submit feedback:', error);
            setSubmitError(error?.response?.data?.detail || 'Failed to submit feedback. Please try again.');
        } finally {
            setSubmitting(false);
        }
    };

    const isSingleChoiceValid = (value) => typeof value === 'string' && value.length > 0;
    const canSubmit = isSingleChoiceValid(consentSelection) && !submitting && !feedbackSubmitted;

    const updateConstraintConsidered = (index, value) => {
        setConstraintResponses((prev) => {
            const next = [...prev];
            const current = next[index] || { considered: '', dimensions: [] };
            next[index] = {
                ...current,
                considered: value,
                dimensions: value === 'yes' ? current.dimensions : [],
            };
            return next;
        });
    };

    const toggleConstraintDimension = (index, dimension) => {
        setConstraintResponses((prev) => {
            const next = [...prev];
            const current = next[index] || { considered: '', dimensions: [] };
            const hasDimension = current.dimensions.includes(dimension);
            const updatedDimensions = hasDimension
                ? current.dimensions.filter((item) => item !== dimension)
                : [...current.dimensions, dimension];
            next[index] = { ...current, dimensions: updatedDimensions };
            return next;
        });
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
                    {surveyConfig.intro}
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
                                <div className="feedback-field-title">{surveyConfig.overall_helpful}</div>
                                <Likert5 name="overall_helpful" value={rating} onChange={setRating} />
                            </div>

                            <div className="feedback-field">
                                <div className="feedback-field-title">{surveyConfig.confidence_before}</div>
                                <Likert5 name="confidence_before" value={confidenceBefore} onChange={setConfidenceBefore} />
                            </div>

                            <div className="feedback-field">
                                <div className="feedback-field-title">{surveyConfig.confidence_after}</div>
                                <Likert5 name="confidence_after" value={confidenceAfter} onChange={setConfidenceAfter} />
                            </div>

                            <div className="feedback-field">
                                <div className="feedback-field-title">{surveyConfig.question_quality}</div>
                                <Likert5 name="question_quality" value={questionQuality} onChange={setQuestionQuality} />
                            </div>

                            <div className="feedback-field">
                                <div className="feedback-field-title">{surveyConfig.new_parameters_prompting}</div>
                                <Likert5 name="new_parameters_prompting" value={newParametersPrompting} onChange={setNewParametersPrompting} />
                            </div>

                            <div className="feedback-field">
                                <div className="feedback-field-title">{surveyConfig.ease_of_use}</div>
                                <Likert5 name="ease_of_use" value={easeOfUse} onChange={setEaseOfUse} leftLabel="Very difficult" rightLabel="Very easy" />
                            </div>

                            <div className="feedback-field">
                                <div className="feedback-field-title">{surveyConfig.felt_in_control}</div>
                                <Likert5 name="felt_in_control" value={feltInControl} onChange={setFeltInControl} />
                            </div>

                            <div className="feedback-field">
                                <div className="feedback-field-title">Tone of the questions</div>
                                <div className="feedback-option-group" role="radiogroup" aria-label="Question tone">
                                    {toneOptions.map((option) => (
                                        <label
                                            key={option.value}
                                            className={`feedback-option ${toneSelection === option.value ? 'selected' : ''}`}
                                        >
                                            <input
                                                type="radio"
                                                name="question_tone"
                                                value={option.value}
                                                checked={toneSelection === option.value}
                                                onChange={() => setToneSelection(option.value)}
                                            />
                                            <div className="feedback-option-content">
                                                <span className="feedback-option-title">{option.label}</span>
                                                <span className="feedback-option-description">{option.description}</span>
                                            </div>
                                        </label>
                                    ))}
                                </div>
                            </div>

                            <div className="feedback-field">
                                <div className="feedback-field-title">Complexity of the questions</div>
                                <div className="feedback-option-group" role="radiogroup" aria-label="Question complexity">
                                    {complexityOptions.map((option) => (
                                        <label
                                            key={option.value}
                                            className={`feedback-option ${complexitySelection === option.value ? 'selected' : ''}`}
                                        >
                                            <input
                                                type="radio"
                                                name="question_complexity"
                                                value={option.value}
                                                checked={complexitySelection === option.value}
                                                onChange={() => setComplexitySelection(option.value)}
                                            />
                                            <div className="feedback-option-content">
                                                <span className="feedback-option-title">{option.label}</span>
                                                <span className="feedback-option-description">{option.description}</span>
                                            </div>
                                        </label>
                                    ))}
                                </div>
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

                        {constraints.length > 0 ? (
                            <div className="feedback-questions">
                                <p className="feedback-prompt">Constraints check (did the chatbot reference these when relevant?)</p>
                                {constraints.map((constraint, index) => {
                                    const response = constraintResponses[index] || { considered: '', dimensions: [] };
                                    const showDimensionPicker = response.considered === 'yes';
                                    return (
                                        <div key={constraint.id} className="constraint-block">
                                            <div className="constraint-header">
                                                <div className="constraint-title">
                                                    {constraint.audience ? `${constraint.label} (${constraint.audience})` : constraint.label}
                                                </div>
                                                <div className="constraint-description">{constraint.description}</div>
                                            </div>
                                            <div className="constraint-yes-no" role="radiogroup" aria-label={`${constraint.label} considered`}>
                                                <label className={`yes-no-option ${response.considered === 'yes' ? 'selected' : ''}`}>
                                                    <input
                                                        type="radio"
                                                        name={`constraint_${constraint.id}`}
                                                        value="yes"
                                                        checked={response.considered === 'yes'}
                                                        onChange={() => updateConstraintConsidered(index, 'yes')}
                                                    />
                                                    <span>Yes</span>
                                                </label>
                                                <label className={`yes-no-option ${response.considered === 'no' ? 'selected' : ''}`}>
                                                    <input
                                                        type="radio"
                                                        name={`constraint_${constraint.id}`}
                                                        value="no"
                                                        checked={response.considered === 'no'}
                                                        onChange={() => updateConstraintConsidered(index, 'no')}
                                                    />
                                                    <span>No</span>
                                                </label>
                                            </div>
                                            {showDimensionPicker && (
                                                <div className="constraint-dimensions">
                                                    <div className="constraint-dimensions-title">Which dimension(s) reflected this constraint?</div>
                                                    {dimensionOptions.length === 0 ? (
                                                        <div className="constraint-empty">No dimensions available to select.</div>
                                                    ) : (
                                                        <div className="dimension-checklist" role="group" aria-label={`${constraint.label} dimensions`}>
                                                            {dimensionOptions.map((dimension) => (
                                                                <label key={dimension} className={`dimension-option ${response.dimensions.includes(dimension) ? 'selected' : ''}`}>
                                                                    <input
                                                                        type="checkbox"
                                                                        value={dimension}
                                                                        checked={response.dimensions.includes(dimension)}
                                                                        onChange={() => toggleConstraintDimension(index, dimension)}
                                                                    />
                                                                    <span>{dimension}</span>
                                                                </label>
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        ) : (
                            <div className="feedback-questions">
                                <p className="feedback-prompt">Constraints check</p>
                                <div className="constraint-empty">
                                    No framework constraints available for this session.
                                </div>
                            </div>
                        )}

                        <div className="feedback-field">
                            <label className="feedback-field-title" htmlFor="mostHelpful">What was the most helpful part of the experience?</label>
                            <textarea
                                id="mostHelpful"
                                value={mostHelpful}
                                onChange={(e) => setMostHelpful(e.target.value)}
                                rows={4}
                            />
                        </div>

                        <div className="feedback-field">
                            <label className="feedback-field-title" htmlFor="improvements">What should we improve?</label>
                            <textarea
                                id="improvements"
                                value={improvements}
                                onChange={(e) => setImprovements(e.target.value)}
                                rows={4}
                            />
                        </div>

                        <div className="feedback-field">
                            <label className="feedback-field-title" htmlFor="otherComments">Anything else you’d like to add?</label>
                            <textarea
                                id="otherComments"
                                value={otherComments}
                                onChange={(e) => setOtherComments(e.target.value)}
                                rows={3}
                            />
                        </div>

                        <div className="feedback-consent">
                            <div className="feedback-field-title">Consent to retain your data</div>
                            <div className="constraint-yes-no" role="radiogroup" aria-label="Consent to retain data">
                                <label className={`yes-no-option ${consentSelection === 'yes' ? 'selected' : ''}`}>
                                    <input
                                        type="radio"
                                        name="consent_to_use_data"
                                        value="yes"
                                        checked={consentSelection === 'yes'}
                                        onChange={() => setConsentSelection('yes')}
                                    />
                                    <span>Yes, keep my data</span>
                                </label>
                                <label className={`yes-no-option ${consentSelection === 'no' ? 'selected' : ''}`}>
                                    <input
                                        type="radio"
                                        name="consent_to_use_data"
                                        value="no"
                                        checked={consentSelection === 'no'}
                                        onChange={() => setConsentSelection('no')}
                                    />
                                    <span>No, delete my data</span>
                                </label>
                            </div>
                            <div className="feedback-consent-note">
                                If you choose no, the system will delete your session data after submission.
                            </div>
                        </div>

                        {submitError ? <div className="feedback-error">{submitError}</div> : null}

                        <button
                            type="submit"
                            className="btn-submit"
                            disabled={!canSubmit}
                        >
                            {submitting ? 'Submitting...' : 'Submit Feedback'}
                        </button>
                    </form>
                )}
            </div>
        </div>
    );
};

export default SynthesisResult;
