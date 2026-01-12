import './CommandHistoryItem.css';

const CommandHistoryItem = ({ command, result }) => {
    const getCommandIcon = (cmdType) => {
        const icons = {
            'status': '📊',
            'steps': '📋',
            'help': '❓',
            'skip': '⏭️',
            'done': '✅',
            'back': '◀️',
            'goto': '🎯',
            'restart': '🔄',
            'submit': '🏁',
            'end': '🏁'
        };
        return icons[cmdType] || '⚡';
    };

    const getStatusClass = () => {
        if (!result) return 'command-pending';
        return result.success ? 'command-success' : 'command-error';
    };

    return (
        <div className={`command-history-item ${getStatusClass()}`}>
            <div className="command-history-header">
                <span className="command-icon">{getCommandIcon(result?.type || command.replace('/', ''))}</span>
                <span className="command-text">{command}</span>
                <span className="command-badge">{result?.type?.toUpperCase() || 'EXECUTED'}</span>
            </div>

            {result && (
                <div className="command-history-body">
                    <div className="command-message">
                        {result.message}
                    </div>

                    {result.step_summary && (
                        <div className="command-summary">
                            <div className="summary-stats">
                                <span className="stat">
                                    <strong>Progress:</strong> {result.step_summary.completed_steps || 0} / {result.step_summary.total_steps || 0}
                                </span>
                                {result.step_summary.pending_steps > 0 && (
                                    <span className="stat">
                                        <strong>Remaining:</strong> {result.step_summary.pending_steps}
                                    </span>
                                )}
                            </div>
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
                                        <span className="step-name">{step.aspect_name}</span>
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
