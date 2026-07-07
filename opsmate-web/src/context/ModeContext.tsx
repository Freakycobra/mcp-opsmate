import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { getMode } from '@/api/admin';
import type { ExecutionMode, ModeConfigurationResponse } from '@/types/api';

export interface ModeContextType {
  /** Current global execution mode */
  mode: ExecutionMode;
  /** Effective mode (accounting for overrides) */
  effectiveMode: ExecutionMode;
  /** Per-server mode overrides */
  serverModes: Record<string, 'mock' | 'live' | 'local'>;
  /** Number of active executions */
  activeExecutions: number;
  /** Whether a mode switch is in progress */
  isLoading: boolean;
  /** Error if mode fetch failed */
  error: string | null;
  /** When the mode was last changed */
  lastChangedAt: string | null;
  /** Fetch the current mode from the server */
  refreshMode: () => Promise<void>;
  /** Whether LIVE mode is active (shows warning) */
  isLiveMode: boolean;
}

const ModeContext = createContext<ModeContextType | null>(null);

const POLL_INTERVAL_MS = 30000; // Poll every 30 seconds

export function ModeProvider({ children }: { children: React.ReactNode }): JSX.Element {
  const [mode, setMode] = useState<ExecutionMode>('mock');
  const [effectiveMode, setEffectiveMode] = useState<ExecutionMode>('mock');
  const [serverModes, setServerModes] = useState<Record<string, 'mock' | 'live' | 'local'>>({});
  const [activeExecutions, setActiveExecutions] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastChangedAt, setLastChangedAt] = useState<string | null>(null);

  const refreshMode = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const config: ModeConfigurationResponse = await getMode();
      setMode(config.global_mode);
      setEffectiveMode(config.effective_mode);
      setServerModes(config.server_modes);
      setActiveExecutions(config.active_executions);
      setLastChangedAt(config.last_changed_at);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch mode configuration';
      setError(message);
      // Fallback: assume mock mode for safety
      setMode('mock');
      setEffectiveMode('mock');
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Initial fetch + polling
  useEffect(() => {
    refreshMode();
    const interval = setInterval(refreshMode, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refreshMode]);

  const value: ModeContextType = {
    mode,
    effectiveMode,
    serverModes,
    activeExecutions,
    isLoading,
    error,
    lastChangedAt,
    refreshMode,
    isLiveMode: effectiveMode === 'live',
  };

  return <ModeContext.Provider value={value}>{children}</ModeContext.Provider>;
}

export function useMode(): ModeContextType {
  const context = useContext(ModeContext);
  if (!context) {
    throw new Error('useMode must be used within a ModeProvider');
  }
  return context;
}

export default ModeContext;
