import { useState, useEffect } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './AuthContext';
import { onboardingApi } from '../services/api';

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading } = useAuth();
  const location = useLocation();
  const [onboardingChecked, setOnboardingChecked] = useState(false);
  const [onboardingComplete, setOnboardingComplete] = useState(true);

  useEffect(() => {
    if (!isAuthenticated || loading) return;
    // Skip onboarding check if already on /onboarding
    if (location.pathname === '/onboarding') {
      setOnboardingChecked(true);
      return;
    }

    onboardingApi.getStatus()
      .then(res => {
        setOnboardingComplete(res.data.completed === true);
      })
      .catch(() => {
        // If API fails, assume onboarding complete (don't block the user)
        setOnboardingComplete(true);
      })
      .finally(() => {
        setOnboardingChecked(true);
      });
  }, [isAuthenticated, loading, location.pathname]);

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <p>Loading...</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  // Wait for onboarding check
  if (!onboardingChecked) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <p>Loading...</p>
      </div>
    );
  }

  // Redirect to onboarding if not complete (and not already on /onboarding)
  if (!onboardingComplete && location.pathname !== '/onboarding') {
    return <Navigate to="/onboarding" replace />;
  }

  return <>{children}</>;
}
