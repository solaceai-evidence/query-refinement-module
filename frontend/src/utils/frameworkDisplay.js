export const formatFrameworkDisplayName = (frameworkId) => {
    if (!frameworkId || typeof frameworkId !== 'string') {
        return '';
    }

    return frameworkId
        .split('_')
        .filter(Boolean)
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
        .join(' ');
};
