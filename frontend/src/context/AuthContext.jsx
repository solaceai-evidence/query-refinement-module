import { createContext, useContext, useState } from 'react';
import { authUtils } from '../utils/auth';
import apiClient from '../services/api';
import { logger } from '../utils/logger';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(() => (authUtils.isAuthenticated() ? authUtils.getUserInfo() : null));
    const [loading] = useState(false);

    const login = async (username, password) => {
        try {
            logger.info('User login attempt', { username });

            const response = await apiClient.post('/auth/login',
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

            const { access_token } = response.data;
            authUtils.setToken(access_token);

            const userInfo = authUtils.getUserInfo();
            setUser(userInfo);

            logger.info('User login successful', { username, userId: userInfo?.sub });

            // Wait for state update to complete before returning
            await new Promise(resolve => setTimeout(resolve, 0));

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

            // Only include email in request if provided (for future production use)
            const requestData = {
                username,
                password,
                ...(email && { email }) // Conditionally add email if it exists
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

    const logout = () => {
        logger.info('User logout', { username: user?.sub });
        authUtils.removeTokens();
        setUser(null);
    };

    const value = {
        user,
        loading,
        login,
        register,
        logout,
        // Check both user state and localStorage to handle race conditions
        isAuthenticated: !!user || authUtils.isAuthenticated()
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
