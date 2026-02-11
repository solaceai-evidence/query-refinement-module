import { createContext, useContext, useState, useCallback, useEffect } from 'react';
import Toast from '../components/Toast';
import { registerToastHandlers } from '../utils/toast';

const ToastContext = createContext();

// eslint-disable-next-line react-refresh/only-export-components
export const useToast = () => {
    const context = useContext(ToastContext);
    if (!context) {
        throw new Error('useToast must be used within ToastProvider');
    }
    return context;
};

export const ToastProvider = ({ children }) => {
    const [toasts, setToasts] = useState([]);

    const removeToast = useCallback((id) => {
        setToasts(prev => prev.filter(toast => toast.id !== id));
    }, []);

    const showToast = useCallback((message, type = 'info', duration = 5000) => {
        const id = Date.now() + Math.random();
        const newToast = { id, message, type, duration };

        setToasts(prev => [...prev, newToast]);

        // Auto-remove after duration
        if (duration > 0) {
            setTimeout(() => {
                removeToast(id);
            }, duration);
        }

        return id;
    }, [removeToast]);

    const showInfo = useCallback((message, duration) => showToast(message, 'info', duration), [showToast]);
    const showSuccess = useCallback((message, duration) => showToast(message, 'success', duration), [showToast]);
    const showWarning = useCallback((message, duration) => showToast(message, 'warning', duration), [showToast]);
    const showError = useCallback((message, duration) => showToast(message, 'error', duration), [showToast]);
    const showLoading = useCallback((message, duration = 0) => showToast(message, 'loading', duration), [showToast]);

    // Register toast handlers for non-React contexts
    useEffect(() => {
        registerToastHandlers({
            showInfo,
            showSuccess,
            showWarning,
            showError,
            showLoading,
            removeToast
        });
    }, [showInfo, showSuccess, showWarning, showError, showLoading, removeToast]);

    return (
        <ToastContext.Provider value={{
            showToast,
            showInfo,
            showSuccess,
            showWarning,
            showError,
            showLoading,
            removeToast
        }}>
            {children}
            <div className="toast-container">
                {toasts.map(toast => (
                    <Toast
                        key={toast.id}
                        message={toast.message}
                        type={toast.type}
                        duration={toast.duration}
                        onClose={() => removeToast(toast.id)}
                    />
                ))}
            </div>
        </ToastContext.Provider>
    );
};
