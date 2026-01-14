import { jwtDecode } from 'jwt-decode';

const TOKEN_KEY = 'auth_token';
const REFRESH_TOKEN_KEY = 'refresh_token';

export const authUtils = {
    // Store tokens
    setToken(token) {
        localStorage.setItem(TOKEN_KEY, token);
    },

    setRefreshToken(token) {
        localStorage.setItem(REFRESH_TOKEN_KEY, token);
    },

    // Get tokens
    getToken() {
        return localStorage.getItem(TOKEN_KEY);
    },

    getRefreshToken() {
        return localStorage.getItem(REFRESH_TOKEN_KEY);
    },

    // Remove tokens
    removeTokens() {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(REFRESH_TOKEN_KEY);
    },

    // Check if token is expired
    isTokenExpired(token) {
        if (!token) return true;

        try {
            const decoded = jwtDecode(token);
            const currentTime = Date.now() / 1000;
            return decoded.exp < currentTime;
        } catch (error) {
            return true;
        }
    },

    // Check if user is authenticated
    isAuthenticated() {
        const token = this.getToken();
        return token && !this.isTokenExpired(token);
    },

    // Get user info from token
    getUserInfo() {
        const token = this.getToken();
        if (!token) return null;

        try {
            return jwtDecode(token);
        } catch (error) {
            return null;
        }
    }
};
