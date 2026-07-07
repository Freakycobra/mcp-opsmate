import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';

export interface AuthState {
  /** User's API key for standard endpoints */
  apiKey: string | null;
  /** Admin bearer token for admin endpoints */
  adminToken: string | null;
  /** Whether the user is authenticated (has API key) */
  isAuthenticated: boolean;
  /** Whether the user has admin privileges */
  isAdmin: boolean;
}

export interface AuthContextType extends AuthState {
  /** Set the API key (persists to localStorage) */
  setApiKey: (key: string | null) => void;
  /** Set the admin token (persists to localStorage) */
  setAdminToken: (token: string | null) => void;
  /** Log out - clear all credentials */
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

const API_KEY_STORAGE_KEY = 'opsmate_api_key';
const ADMIN_TOKEN_STORAGE_KEY = 'opsmate_admin_token';

export function AuthProvider({ children }: { children: React.ReactNode }): JSX.Element {
  const [apiKey, setApiKeyState] = useState<string | null>(() => {
    try {
      return localStorage.getItem(API_KEY_STORAGE_KEY);
    } catch {
      return null;
    }
  });

  const [adminToken, setAdminTokenState] = useState<string | null>(() => {
    try {
      return localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY);
    } catch {
      return null;
    }
  });

  // Persist API key to localStorage
  useEffect(() => {
    if (apiKey) {
      localStorage.setItem(API_KEY_STORAGE_KEY, apiKey);
    } else {
      localStorage.removeItem(API_KEY_STORAGE_KEY);
    }
  }, [apiKey]);

  // Persist admin token to localStorage
  useEffect(() => {
    if (adminToken) {
      localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, adminToken);
    } else {
      localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
    }
  }, [adminToken]);

  const setApiKey = useCallback((key: string | null) => {
    setApiKeyState(key);
  }, []);

  const setAdminToken = useCallback((token: string | null) => {
    setAdminTokenState(token);
  }, []);

  const logout = useCallback(() => {
    setApiKeyState(null);
    setAdminTokenState(null);
    localStorage.removeItem(API_KEY_STORAGE_KEY);
    localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
  }, []);

  const value: AuthContextType = {
    apiKey,
    adminToken,
    isAuthenticated: apiKey !== null && apiKey.length > 0,
    isAdmin: adminToken !== null && adminToken.length > 0,
    setApiKey,
    setAdminToken,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

export default AuthContext;
