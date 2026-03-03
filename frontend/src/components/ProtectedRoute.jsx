import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { authUtils } from '../utils/auth';

const ProtectedRoute = ({ children }) => {
    const { isAuthenticated, loading } = useAuth();

    if (loading) {
        return (
            <div style={{
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                height: '100vh'
            }}>
                Loading...
            </div>
        );
    }

    // Check both context and localStorage to handle race conditions
    const hasValidAuth = isAuthenticated || authUtils.isAuthenticated();
    return hasValidAuth ? children : <Navigate to="/login" replace />;
};

export default ProtectedRoute;
