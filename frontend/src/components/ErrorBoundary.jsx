import React from 'react';
import { logger } from '../utils/logger';
import './ErrorBoundary.css';

class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = {
            hasError: false,
            error: null,
            errorInfo: null
        };
    }

    static getDerivedStateFromError(error) {
        // Update state so the next render will show the fallback UI
        return { hasError: true, error };
    }

    componentDidCatch(error, errorInfo) {
        // Log the error to our logging service
        logger.error('React Error Boundary caught error', error, {
            componentStack: errorInfo.componentStack,
            errorBoundary: true
        });

        // Store error details in state
        this.setState({
            error,
            errorInfo
        });
    }

    handleReload = () => {
        // Clear any potentially corrupt state
        try {
            localStorage.removeItem('refinement_session');
        } catch (err) {
            logger.debug('Failed to clear refinement_session from localStorage', { err });
        }
        window.location.reload();
    };

    handleGoHome = () => {
        // Clear state and go to home
        try {
            localStorage.removeItem('refinement_session');
        } catch (err) {
            logger.debug('Failed to clear refinement_session from localStorage', { err });
        }
        window.location.href = '/';
    };

    render() {
        if (this.state.hasError) {
            return (
                <div className="error-boundary">
                    <div className="error-boundary-content">
                        <div className="error-icon">⚠️</div>
                        <h1>Oops! Something went wrong</h1>
                        <p className="error-message">
                            We're sorry, but something unexpected happened.
                            Your progress has been saved, and you can try refreshing the page.
                        </p>

                        <div className="error-actions">
                            <button
                                onClick={this.handleReload}
                                className="btn-primary"
                            >
                                Reload Page
                            </button>
                            <button
                                onClick={this.handleGoHome}
                                className="btn-secondary"
                            >
                                Go to Home
                            </button>
                        </div>

                        {import.meta.env.MODE === 'development' && this.state.error && (
                            <details className="error-details">
                                <summary>Technical Details (Development Only)</summary>
                                <div className="error-stack">
                                    <p><strong>Error:</strong> {this.state.error.toString()}</p>
                                    {this.state.errorInfo && (
                                        <pre>{this.state.errorInfo.componentStack}</pre>
                                    )}
                                </div>
                            </details>
                        )}
                    </div>
                </div>
            );
        }

        return this.props.children;
    }
}

export default ErrorBoundary;
