import './AspectStatusPanel.css';

const AspectStatusPanel = ({ aspects }) => {
    if (!aspects || aspects.length === 0) {
        return null;
    }

    const getStatusIcon = (isComplete) => {
        if (isComplete === true) {
            return '✓';
        } else if (isComplete === false) {
            return '⟳';
        }
        return '?';
    };

    const getStatusClass = (isComplete) => {
        if (isComplete === true) return 'status-complete';
        if (isComplete === false) return 'status-incomplete';
        return 'status-unknown';
    };

    const getStatusLabel = (isComplete) => {
        if (isComplete === true) return 'complete';
        if (isComplete === false) return 'incomplete';
        return 'unknown';
    };

    return (
        <div className="aspect-status-panel">
            <h3>Refinement Progress</h3>
            <div className="aspects-list">
                {aspects.map((aspect, index) => (
                    <div
                        key={aspect.id || aspect.aspect_id || index}
                        className={`aspect-item ${getStatusClass(aspect.is_complete)}`}
                    >
                        <span className="status-icon">{getStatusIcon(aspect.is_complete)}</span>
                        <span className="aspect-name">{aspect.name || aspect.aspect_name || aspect.id}</span>
                        <span className="status-badge">{getStatusLabel(aspect.is_complete)}</span>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default AspectStatusPanel;
