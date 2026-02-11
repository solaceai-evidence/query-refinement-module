import { useState } from 'react';
import './CommandHistoryItem.css';
import { getCommandIcon } from '../constants/commands';

/**
 * @typedef {import('../types/api').CommandHistoryItemProps} CommandHistoryItemProps
 * @typedef {import('../types/api').CommandResult} CommandResult
 * @typedef {import('../types/api').StepListItem} StepListItem
 */

/**
 * Expandable dimension card component
 */
const DimensionCard = ({ dimension }) => {
    const [isExpanded, setIsExpanded] = useState(false);

    return (
        <div
            className={`dimension-item ${dimension.status} ${dimension.is_active ? 'active' : ''} ${isExpanded ? 'expanded' : ''}`}
        >
            <div
                className="dimension-header clickable"
                onClick={() => setIsExpanded(!isExpanded)}
                role="button"
                tabIndex={0}
                onKeyPress={(e) => e.key === 'Enter' && setIsExpanded(!isExpanded)}
            >
                <span className="expand-icon">{isExpanded ? '▼' : '▶'}</span>
                <span className="dimension-icon">{dimension.status_icon}</span>
                <span className="dimension-name">{dimension.name}</span>
                <span className={`dimension-badge ${dimension.status}`}>
                    {dimension.status.replace('_', ' ')}
                </span>
            </div>

            {/* Always visible summary */}
            {dimension.assembled_value && (
                <div className="dimension-value">
                    <strong>Assembled:</strong> {dimension.assembled_value}
                </div>
            )}
            {dimension.follow_up_count > 0 && (
                <div className="dimension-followups">
                    <span className="followup-icon">💬</span>
                    {dimension.follow_up_count} follow-up{dimension.follow_up_count !== 1 ? 's' : ''}
                </div>
            )}
            {dimension.was_skipped && (
                <div className="dimension-skipped">
                    <em>Dimension skipped - no specification provided</em>
                </div>
            )}

            {/* Expanded details */}
            {isExpanded && (
                <div className="dimension-expanded-content">
                    {dimension.assembled_value && (
                        <div className="dimension-assembled-expanded">
                            <strong>Assembled Specification:</strong>
                            <p className="assembled-value-text">{dimension.assembled_value}</p>
                        </div>
                    )}

                    {dimension.description && (
                        <div className="dimension-description">
                            <strong>Description:</strong>
                            <p>{dimension.description}</p>
                        </div>
                    )}

                    {dimension.depends_on && dimension.depends_on.length > 0 && (
                        <div className="dimension-dependencies">
                            <strong>Dependencies:</strong>
                            <div className="dependency-list">
                                {dimension.depends_on.map((dep, idx) => (
                                    <span key={idx} className="dependency-tag">{dep}</span>
                                ))}
                            </div>
                        </div>
                    )}

                    {dimension.conversation_history && dimension.conversation_history.length > 0 && (
                        <div className="dimension-conversation">
                            <strong>Conversation History:</strong>
                            <div className="conversation-list">
                                {dimension.conversation_history.map((exchange, idx) => (
                                    <div key={idx} className="conversation-exchange">
                                        <div className="conversation-question">
                                            <span className="exchange-label">Q{idx + 1}:</span>
                                            <span className="exchange-text">{exchange.question}</span>
                                        </div>
                                        <div className="conversation-response">
                                            <span className="exchange-label">A{idx + 1}:</span>
                                            <span className="exchange-text">{exchange.response}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

/**
 * Component for displaying executed command in conversation history
 * @param {CommandHistoryItemProps} props
 * @returns {JSX.Element}
 */
const CommandHistoryItem = ({ command, result }) => {

    const getStatusClass = () => {
        if (!result) return 'command-pending';
        return result.success ? 'command-success' : 'command-error';
    };

    // Debug logging
    if (result) {
        console.log('[CommandHistoryItem] Rendering command:', command);
        console.log('[CommandHistoryItem] Result:', result);
        console.log('[CommandHistoryItem] Has step_summary?', !!result.step_summary);
        console.log('[CommandHistoryItem] Has step_list?', !!result.step_list);
        if (result.step_summary) {
            console.log('[CommandHistoryItem] step_summary content:', JSON.stringify(result.step_summary, null, 2));
        }
    }

    return (
        <div className={`command-history-item ${getStatusClass()}`}>
            <div className="command-history-header">
                <span className="command-icon">{getCommandIcon(result?.type || command)}</span>
                <span className="command-text">{command}</span>
                <span className="command-badge">{result?.type?.toUpperCase() || 'EXECUTED'}</span>
            </div>

            {result && (
                <div className="command-history-body">
                    {/* Only show plain text message if no GUI components are available */}
                    {!result.step_summary && !result.step_list && (
                        <div className="command-message">
                            {result.message.split('\n').map((line, idx) => (
                                <div key={idx}>{line || '\u00A0'}</div>
                            ))}
                        </div>
                    )}

                    {result.step_summary && (
                        <div className="command-summary">
                            {/* Framework Context */}
                            {result.step_summary.framework_context && (
                                <div className="framework-context">
                                    <div className="context-label">
                                        <span className="context-icon">🎯</span>
                                        <strong>Framework Context:</strong>
                                    </div>
                                    <div className="context-details">
                                        <span className="context-item">
                                            <strong>User Type:</strong> {result.step_summary.framework_context.user_type}
                                        </span>
                                        {result.step_summary.framework_context.tone && (
                                            <span className="context-item">
                                                <strong>Tone:</strong> {result.step_summary.framework_context.tone}
                                            </span>
                                        )}
                                        {result.step_summary.framework_context.complexity && (
                                            <span className="context-item">
                                                <strong>Complexity:</strong> {result.step_summary.framework_context.complexity}
                                            </span>
                                        )}
                                    </div>
                                </div>
                            )}

                            {/* Summary Stats */}
                            <div className="summary-stats">
                                <span className="stat">
                                    <strong>Progress:</strong> {result.step_summary.completed_steps || 0} / {result.step_summary.total_steps || 0}
                                </span>
                                {result.step_summary.pending_steps > 0 && (
                                    <span className="stat">
                                        <strong>Remaining:</strong> {result.step_summary.pending_steps}
                                    </span>
                                )}
                                {result.step_summary.total_follow_ups > 0 && (
                                    <span className="stat">
                                        <strong>Follow-ups:</strong> {result.step_summary.total_follow_ups}
                                    </span>
                                )}
                            </div>

                            {/* Detailed Dimension Status */}
                            {result.step_summary.dimensions && result.step_summary.dimensions.length > 0 && (
                                <div className="dimensions-detail">
                                    <div className="dimensions-header">
                                        <span className="dimensions-icon">📊</span>
                                        <strong>Dimension Status:</strong>
                                    </div>
                                    <div className="dimensions-list">
                                        {result.step_summary.dimensions.map((dim, idx) => (
                                            <DimensionCard key={idx} dimension={dim} />
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {result.step_list && (
                        <div className="command-steps-list">
                            <div className="steps-header">Refinement Steps:</div>
                            <div className="steps-grid">
                                {result.step_list.map((step, idx) => (
                                    <div
                                        key={idx}
                                        className={`step-badge ${step.is_active ? 'active' : ''} ${step.status === 'completed' ? 'complete' : ''}`}
                                    >
                                        <span className="step-number">{idx + 1}</span>
                                        <span className="step-name">{step.name}</span>
                                        <span className="step-status">{step.status}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {result.invalidated_aspects && result.invalidated_aspects.length > 0 && (
                        <div className="command-warning">
                            <strong>⚠️ Invalidated aspects:</strong> {result.invalidated_aspects.join(', ')}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default CommandHistoryItem;
