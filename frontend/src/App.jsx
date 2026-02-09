import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { useEffect } from 'react';
import { AuthProvider } from './context/AuthContext';
import { ToastProvider } from './context/ToastContext';
import ErrorBoundary from './components/ErrorBoundary';
import ProtectedRoute from './components/ProtectedRoute';
import Login from './pages/Login';
import Register from './pages/Register';
import Refinement from './pages/Refinement';
import './App.css';

// Import log forwarder to initialize it
import './utils/logForwarder';
import { logger } from './utils/logger';

function App() {
  useEffect(() => {
    // Log app initialization
    logger.info('Application initialized', {
      env: import.meta.env.MODE,
      timestamp: new Date().toISOString()
    });
  }, []);

  return (
    <ErrorBoundary>
      <Router>
        <ToastProvider>
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />
              <Route
                path="/"
                element={
                  <ProtectedRoute>
                    <Refinement />
                  </ProtectedRoute>
                }
              />
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </AuthProvider>
        </ToastProvider>
      </Router>
    </ErrorBoundary>
  );
}

export default App;
