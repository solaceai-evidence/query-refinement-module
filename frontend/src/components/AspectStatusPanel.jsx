import './AspectStatusPanel.css';

const AspectStatusPanel = ({ aspects }) => {
    if (!aspects || aspects.length === 0) {
        return null;
    }

    const getStatusIcon = (status) => {
        switch (status) {
            case 'complete':
                return '✓';
            case 'needs_refinement':
                return '⟳';
            case 'clear':
                return '○';
            default:
                return '?';
        }
    };

    const getStatusClass = (status) => {
        return `status-${status.replace('_', '-')}`;
    };

    return (
        <div className="aspect-status-panel">
            <h3>Refinement Progress</h3>
            <div className="aspects-list">
                {aspects.map((aspect, index) => (
                    <div
                        key={aspect.aspect_id || index}
                        className={`aspect-item ${getStatusClass(aspect.status)}`}
                    >
                        <span className="status-icon">{getStatusIcon(aspect.status)}</span>
                        <span className="aspect-name">{aspect.aspect_id}</span>
                        <span className="status-badge">{aspect.status.replace('_', ' ')}</span>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default AspectStatusPanel;
