import { useEffect } from 'react';
import './Toast.css';

const Toast = ({ message, type = 'info', duration = 5000, onClose }) => {
    useEffect(() => {
        if (duration > 0) {
            const timer = setTimeout(() => {
                onClose?.();
            }, duration);
            return () => clearTimeout(timer);
        }
    }, [duration, onClose]);

    const icons = {
        info: 'ℹ️',
        success: '✅',
        warning: '⚠️',
        error: '❌',
        loading: '⏳'
    };

    return (
        <div className={`toast toast-${type}`}>
            <span className="toast-icon">{icons[type] || icons.info}</span>
            <span className="toast-message">{message}</span>
            {onClose && (
                <button className="toast-close" onClick={onClose}>
                    ×
                </button>
            )}
        </div>
    );
};

export default Toast;
