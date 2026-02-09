// Global toast manager for non-React contexts (like api.js)
let toastHandlers = {
    showInfo: null,
    showSuccess: null,
    showWarning: null,
    showError: null,
    showLoading: null,
    removeToast: null
};

export const registerToastHandlers = (handlers) => {
    toastHandlers = { ...handlers };
};

export const toast = {
    info: (message, duration) => {
        if (toastHandlers.showInfo) {
            return toastHandlers.showInfo(message, duration);
        }
        console.info(message);
    },
    success: (message, duration) => {
        if (toastHandlers.showSuccess) {
            return toastHandlers.showSuccess(message, duration);
        }
        console.log(message);
    },
    warning: (message, duration) => {
        if (toastHandlers.showWarning) {
            return toastHandlers.showWarning(message, duration);
        }
        console.warn(message);
    },
    error: (message, duration) => {
        if (toastHandlers.showError) {
            return toastHandlers.showError(message, duration);
        }
        console.error(message);
    },
    loading: (message, duration) => {
        if (toastHandlers.showLoading) {
            return toastHandlers.showLoading(message, duration);
        }
        console.log(message);
    },
    remove: (id) => {
        if (toastHandlers.removeToast) {
            toastHandlers.removeToast(id);
        }
    }
};
