import { useState } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { Shield, LogIn, UserPlus } from 'lucide-react';
import './LoginPage.css';

export default function LoginPage() {
  const { isAuthenticated, needsBootstrap, login, bootstrap, loading, error: authError, clearError } = useAuth();
  const [mode, setMode] = useState<'login' | 'bootstrap'>(needsBootstrap ? 'bootstrap' : 'login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [orgName, setOrgName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (loading) {
    return (
      <div className="login-container">
        <p>Loading...</p>
      </div>
    );
  }

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  // Merge local form errors with auth context errors
  const displayError = error || authError;

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    clearError();
    setSubmitting(true);
    try {
      await login(email, password);
    } catch {
      // Error is set by AuthContext
    } finally {
      setSubmitting(false);
    }
  };

  const handleBootstrap = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    clearError();
    setSubmitting(true);
    try {
      await bootstrap(orgName, email, password, name || 'Admin');
    } catch {
      // Error is set by AuthContext
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-card">
        <div className="login-header">
          <Shield size={48} className="login-logo" />
          <h1>Renaissance</h1>
          <p className="login-subtitle">Creating Art through Science</p>
          <p className="login-founders">by El Templo Labs</p>
        </div>

        {needsBootstrap && mode === 'login' && (
          <div className="login-notice">
            <p>No organization found. <button type="button" className="link-btn" onClick={() => setMode('bootstrap')}>Set up your workspace</button> first.</p>
          </div>
        )}

        {displayError && (
          <div className="login-error">
            <p>{displayError}</p>
          </div>
        )}

        {mode === 'login' ? (
          <form onSubmit={handleLogin} className="login-form">
            <div className="form-group">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@example.com"
                required
                autoFocus
              />
            </div>
            <div className="form-group">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                required
              />
            </div>
            <button type="submit" className="btn btn-primary login-btn" disabled={submitting}>
              <LogIn size={18} />
              {submitting ? 'Signing in...' : 'Sign In'}
            </button>

            {needsBootstrap && (
              <p className="login-switch">
                First time? <button type="button" className="link-btn" onClick={() => setMode('bootstrap')}>Create workspace</button>
              </p>
            )}
          </form>
        ) : (
          <form onSubmit={handleBootstrap} className="login-form">
            <h2 className="bootstrap-title">Create Your Workspace</h2>
            <div className="form-group">
              <label htmlFor="orgName">Organization Name</label>
              <input
                id="orgName"
                type="text"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                placeholder="My Company"
                required
                autoFocus
              />
            </div>
            <div className="form-group">
              <label htmlFor="bsName">Your Name</label>
              <input
                id="bsName"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Admin"
              />
            </div>
            <div className="form-group">
              <label htmlFor="bsEmail">Admin Email</label>
              <input
                id="bsEmail"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@example.com"
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="bsPassword">Password</label>
              <input
                id="bsPassword"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Choose a strong password"
                required
                minLength={6}
              />
            </div>
            <button type="submit" className="btn btn-primary login-btn" disabled={submitting}>
              <UserPlus size={18} />
              {submitting ? 'Setting up...' : 'Create Workspace & Login'}
            </button>

            <p className="login-switch">
              Already have an account? <button type="button" className="link-btn" onClick={() => setMode('login')}>Sign in</button>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
