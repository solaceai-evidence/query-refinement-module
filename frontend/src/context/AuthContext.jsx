import { createContext, useContext, useState, useEffect } from 'react';
import apiClient from '../services/api';
import { logger } from '../utils/logger';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    // On mount, check whether an httpOnly auth cookie exists by calling /auth/me.
    // This is the only reliable way to restore session state after a page refresh
    // since the cookie is not readable from JavaScript.
    useEffect(() => {
        apiClient.get('/auth/me')
            .then(res => {
                setUser({ sub: res.data.username, ...res.data });
            })
            .catch(() => {
                setUser(null);
            })
            .finally(() => {
                setLoading(false);
            });
    }, []);

    const login = async (username, password) => {
        try {
            logger.info('User login attempt', { username });

            await apiClient.post('/auth/login',
                new URLSearchParams({
                    username,
                    password,
                    grant_type: 'password'
                }),
                {
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded'
                    }
                }
            );

            // Fetch full user profile now that the cookie is set
            const meRes = await apiClient.get('/auth/me');
            const userInfo = { sub: meRes.data.username, ...meRes.data };
            setUser(userInfo);

            logger.info('User login successful', { username, userId: userInfo?.id });

            return { success: true };
        } catch (error) {
            logger.warn('User login failed', {
                username,
                error: error.response?.data?.detail || error.message
            });
            return {
                success: false,
                error: error.response?.data?.detail || 'Login failed'
            };
        }
    };

    const register = async (username, password, email = undefined) => {
        try {
            logger.info('User registration attempt', { username, hasEmail: !!email });

            const requestData = {
                username,
                password,
                ...(email && { email })
            };

            await apiClient.post('/auth/register', requestData);

            logger.info('User registration successful', { username });

            // Auto-login after registration
            return await login(username, password);
        } catch (error) {
            logger.warn('User registration failed', {
                username,
                error: error.response?.data?.detail || error.message
            });
            return {
                success: false,
                error: error.response?.data?.detail || 'Registration failed'
            };
        }
    };

    const logout = async () => {
        logger.info('User logout', { username: user?.sub });
        try {
            // Tell the server to clear the httpOnly cookie
            await apiClient.post('/auth/logout');
        } catch {
            // Ignore errors — we still clear client-side state
        }
        setUser(null);
    };

    const value = {
        user,
        loading,
        login,
        register,
        logout,
        isAuthenticated: !!user,
    };

    return (
        <AuthContext.Provider value={value}>
            {children}
        </AuthContext.Provider>
    );
};

// eslint-disable-next-line react-refresh/only-export-components
export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
};
