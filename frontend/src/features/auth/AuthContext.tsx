/* eslint-disable react-refresh/only-export-components -- provider + hook co-located by design */
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { api, getToken, setToken } from '../../api/client';

interface AuthValue {
  authenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState<boolean>(getToken() !== null);

  // The client fires this when a request 401s with a token present (expired
  // session) — drop to the login screen instead of a broken authenticated shell.
  useEffect(() => {
    const onUnauthorized = () => setAuthenticated(false);
    window.addEventListener('spidey:unauthorized', onUnauthorized);
    return () => window.removeEventListener('spidey:unauthorized', onUnauthorized);
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      authenticated,
      login: async (email, password) => {
        await api.login(email, password);
        setAuthenticated(true);
      },
      logout: () => {
        setToken(null);
        setAuthenticated(false);
      },
    }),
    [authenticated],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used within AuthProvider');
  return value;
}
