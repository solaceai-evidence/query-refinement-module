/**
 * Auth utilities — cookie-based session model.
 *
 * The JWT lives in an httpOnly cookie and is never accessible to JavaScript.
 * Auth state is managed entirely in React (AuthContext) by calling /auth/me on
 * mount.  These helpers exist only to support the AuthContext interface; all
 * localStorage token storage has been removed.
 */

export const authUtils = {
    // No-ops kept for call-site compatibility during the migration.
    // The token is now an httpOnly cookie managed by the browser.
    setToken(_token) { },
    setRefreshToken(_token) { },
    getToken() { return null; },
    getRefreshToken() { return null; },
    removeTokens() { },

    // isTokenExpired is no longer meaningful (token is httpOnly); always false.
    isTokenExpired(_token) { return false; },

    // isAuthenticated must NOT be called for security checks — use the
    // `isAuthenticated` value from AuthContext (populated via /auth/me) instead.
    // This shim returns false so legacy call-sites fail safely rather than
    // granting access without a server-verified session.
    isAuthenticated() { return false; },

    // getUserInfo is no longer available (token is httpOnly).
    getUserInfo() { return null; },
};
