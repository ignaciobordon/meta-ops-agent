import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import api from '../services/api';
import { useStore } from '../store';

interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: string;
  org_id: string;
}

export type AuthStatus = 'idle' | 'loading' | 'authenticated' | 'unauthenticated' | 'refreshing' | 'error';

interface AuthState {
  user: AuthUser | null;
  status: AuthStatus;
  error: string | null;
  /** @deprecated Use status === 'authenticated' */
  isAuthenticated: boolean;
  /** @deprecated Use status === 'loading' || status === 'idle' */
  loading: boolean;
  needsBootstrap: boolean;
  login: (email: string, password: string) => Promise<void>;
  bootstrap: (orgName: string, email: string, password: string, name: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<boolean>;
  clearError: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

const TOKEN_KEYS = {
  access: 'meta_ops_access_token',
  refresh: 'meta_ops_refresh_token',
};

function getStoredToken(key: string): string | null {
  return localStorage.getItem(key);
}

function storeTokens(access: string, refresh: string) {
  localStorage.setItem(TOKEN_KEYS.access, access);
  localStorage.setItem(TOKEN_KEYS.refresh, refresh);
}

function clearTokens() {
  localStorage.removeItem(TOKEN_KEYS.access);
  localStorage.removeItem(TOKEN_KEYS.refresh);
}

export function getAccessToken(): string | null {
  return getStoredToken(TOKEN_KEYS.access);
}

export function getRefreshToken(): string | null {
  return getStoredToken(TOKEN_KEYS.refresh);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [needsBootstrap, setNeedsBootstrap] = useState(false);
  const { setCurrentUser, setCurrentOrg } = useStore();

  // Backward-compatible computed properties
  const isAuthenticated = status === 'authenticated';
  const loading = status === 'idle' || status === 'loading';

  const clearError = useCallback(() => setError(null), []);

  const populateStore = useCallback(async (authUser: AuthUser) => {
    setCurrentUser({
      id: authUser.id,
      email: authUser.email,
      name: authUser.name,
      role: authUser.role,
    });

    try {
      const orgsRes = await api.get('/orgs/');
      const orgs = orgsRes.data;
      const userOrg = orgs.find((o: any) => o.id === authUser.org_id) || orgs[0];
      if (userOrg) {
        setCurrentOrg(userOrg);
      }
    } catch {
      // org load failed, non-critical
    }
  }, [setCurrentUser, setCurrentOrg]);

  const loadMe = useCallback(async (): Promise<AuthUser | null> => {
    const token = getAccessToken();
    if (!token) return null;

    try {
      const res = await api.get('/auth/me');
      return res.data as AuthUser;
    } catch {
      return null;
    }
  }, []);

  const checkBootstrap = useCallback(async () => {
    try {
      const res = await api.get('/auth/bootstrap-check');
      setNeedsBootstrap(res.data.needs_bootstrap);
      return res.data.needs_bootstrap;
    } catch {
      return false;
    }
  }, []);

  // Initialize auth state on mount
  useEffect(() => {
    const init = async () => {
      setStatus('loading');
      const token = getAccessToken();
      if (token) {
        const me = await loadMe();
        if (me) {
          setUser(me);
          setStatus('authenticated');
          await populateStore(me);
        } else {
          clearTokens();
          await checkBootstrap();
          setStatus('unauthenticated');
        }
      } else {
        await checkBootstrap();
        setStatus('unauthenticated');
      }
    };
    init();
  }, [loadMe, checkBootstrap, populateStore]);

  const login = async (email: string, password: string) => {
    setStatus('loading');
    setError(null);
    try {
      const res = await api.post('/auth/login', { email, password });
      const { access_token, refresh_token, user: userData } = res.data;
      storeTokens(access_token, refresh_token);
      const authUser: AuthUser = userData;
      setUser(authUser);
      setStatus('authenticated');
      setNeedsBootstrap(false);
      await populateStore(authUser);
    } catch (err: any) {
      const statusCode = err.response?.status;
      const detail = err.response?.data?.detail;

      if (statusCode === 429) {
        setError(detail || 'Too many login attempts. Please wait before trying again.');
      } else if (statusCode === 401) {
        setError(detail || 'Invalid email or password.');
      } else if (err.code === 'ERR_NETWORK') {
        setError('Cannot connect to server. Please check if the backend is running.');
      } else {
        setError(detail || 'Login failed. Please try again.');
      }
      setStatus('unauthenticated');
      throw err;
    }
  };

  const bootstrap = async (orgName: string, email: string, password: string, name: string) => {
    setStatus('loading');
    setError(null);
    try {
      const res = await api.post('/auth/bootstrap', {
        org_name: orgName,
        admin_email: email,
        admin_password: password,
        admin_name: name,
      });
      const { access_token, refresh_token, user: userData } = res.data;
      storeTokens(access_token, refresh_token);
      const authUser: AuthUser = userData;
      setUser(authUser);
      setStatus('authenticated');
      setNeedsBootstrap(false);
      await populateStore(authUser);
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      if (err.code === 'ERR_NETWORK') {
        setError('Cannot connect to server. Please check if the backend is running.');
      } else {
        setError(detail || 'Bootstrap failed.');
      }
      setStatus('unauthenticated');
      throw err;
    }
  };

  const logout = () => {
    // Call backend logout (fire-and-forget)
    const token = getAccessToken();
    if (token) {
      api.post('/auth/logout').catch(() => {});
    }
    clearTokens();
    setUser(null);
    setStatus('unauthenticated');
    setError(null);
    setCurrentUser(null);
    setCurrentOrg(null);
  };

  const refresh = async (): Promise<boolean> => {
    const refreshTok = getRefreshToken();
    if (!refreshTok) return false;

    // Only show refreshing status if not already authenticated (prevents flicker)
    if (status !== 'authenticated') {
      setStatus('refreshing');
    }

    try {
      const res = await api.post('/auth/refresh', { refresh_token: refreshTok });
      const { access_token, refresh_token: newRefresh, user: userData } = res.data;
      storeTokens(access_token, newRefresh);
      const authUser: AuthUser = userData;
      setUser(authUser);
      setStatus('authenticated');
      return true;
    } catch {
      clearTokens();
      setUser(null);
      setStatus('unauthenticated');
      return false;
    }
  };

  return (
    <AuthContext.Provider value={{
      user, status, error, isAuthenticated, loading, needsBootstrap,
      login, bootstrap, logout, refresh, clearError,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
