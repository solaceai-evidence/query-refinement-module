import './ConfirmationDialog.css';

const ConfirmationDialog = ({ isOpen, title, message, onConfirm, onCancel, confirmText = 'Continue', cancelText = 'Cancel', type = 'warning' }) => {
    if (!isOpen) return null;

    const getIcon = () => {
        switch (type) {
            case 'warning':
                return '⚠️';
            case 'danger':
                return '❌';
            case 'info':
                return 'ℹ️';
            default:
                return '⚠️';
        }
    };

    return (
        <div className="confirmation-dialog-overlay" onClick={onCancel}>
            <div className="confirmation-dialog" onClick={(e) => e.stopPropagation()}>
                <div className={`confirmation-dialog-header ${type}`}>
                    <span className="confirmation-icon">{getIcon()}</span>
                    <h3>{title}</h3>
                </div>
                <div className="confirmation-dialog-body">
                    <p>{message}</p>
                </div>
                <div className="confirmation-dialog-actions">
                    <button
                        className="btn-cancel"
                        onClick={onCancel}
                    >
                        {cancelText}
                    </button>
                    <button
                        className={`btn-confirm ${type}`}
                        onClick={onConfirm}
                    >
                        {confirmText}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ConfirmationDialog;
