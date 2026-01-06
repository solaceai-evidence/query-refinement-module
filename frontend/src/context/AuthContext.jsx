import { createContext, useContext, useState, useEffect } from 'react';
import { authUtils } from '../utils/auth';
import apiClient from '../services/api';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        // Check if user is already authenticated
        if (authUtils.isAuthenticated()) {
            const userInfo = authUtils.getUserInfo();
            setUser(userInfo);
        }
        setLoading(false);
    }, []);

    const login = async (username, password) => {
        try {
            const response = await apiClient.post('/api/auth/token',
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

            return { success: true };
        } catch (error) {
            return {
                success: false,
                error: error.response?.data?.detail || 'Login failed'
            };
        }
    };

    const register = async (username, password, email) => {
        try {
            await apiClient.post('/api/auth/register', {
                username,
                password,
                email
            });

            // Auto-login after registration
            return await login(username, password);
        } catch (error) {
            return {
                success: false,
                error: error.response?.data?.detail || 'Registration failed'
            };
        }
    };

    const logout = () => {
        authUtils.removeTokens();
        setUser(null);
    };

    const value = {
        user,
        loading,
        login,
        register,
        logout,
        isAuthenticated: !!user
    };

    return (
        <AuthContext.Provider value={value}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
};
