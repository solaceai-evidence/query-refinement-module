import { useMemo } from 'react';
import './ProgressIndicator.css';

/**
 * Progress indicator component for refinement workflow
 * 
 * @param {object} props
 * @param {object|null} props.progress - Progress data from API
 * @param {boolean} props.compact - Compact mode (show only bar)
 */
const ProgressIndicator = ({ progress, compact = false }) => {
    const percentage = Math.round(((progress?.progress) || 0) * 100);
    const stage = progress?.stage || 'unknown';
    const message = progress?.message || 'Processing...';

    // Format stage for display
    const displayStage = useMemo(() => {
        return stage
            .split('_')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');
    }, [stage]);

    if (!progress) return null;

    // Get stage color
    const getStageColor = () => {
        if (stage.includes('failed')) return '#ef4444';
        if (stage.includes('complete')) return '#10b981';
        if (stage.includes('waiting')) return '#f59e0b';
        return '#667eea';
    };

    const stageColor = getStageColor();

    if (compact) {
        return (
            <div className="progress-indicator compact">
                <div className="progress-bar">
                    <div
                        className="progress-fill"
                        style={{
                            width: `${percentage}%`,
                            backgroundColor: stageColor
                        }}
                    />
                </div>
                <div className="progress-label">{message}</div>
            </div>
        );
    }

    return (
        <div className="progress-indicator">
            <div className="progress-header">
                <span className="progress-stage" style={{ color: stageColor }}>
                    {displayStage}
                </span>
                <span className="progress-percentage">{percentage}%</span>
            </div>

            <div className="progress-bar">
                <div
                    className="progress-fill"
                    style={{
                        width: `${percentage}%`,
                        backgroundColor: stageColor
                    }}
                />
            </div>

            <div className="progress-message">{message}</div>

            {progress.elapsed_seconds > 0 && (
                <div className="progress-metadata">
                    {progress.llm_calls_made > 0 && (
                        <span className="progress-meta-item">
                            🤖 {progress.llm_calls_made} LLM call{progress.llm_calls_made !== 1 ? 's' : ''}
                        </span>
                    )}
                    {progress.turn_number && progress.total_turns && (
                        <span className="progress-meta-item">
                            📊 Turn {progress.turn_number} of {progress.total_turns}
                        </span>
                    )}
                    <span className="progress-meta-item">
                        ⏱️ {Math.round(progress.elapsed_seconds)}s
                    </span>
                </div>
            )}

            {progress.error && (
                <div className="progress-error">
                    ⚠️ {progress.error}
                </div>
            )}
        </div>
    );
};

export default ProgressIndicator;
