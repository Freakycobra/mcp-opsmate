import React, { useState, useCallback } from 'react';
import { useMode } from '@/context/ModeContext';
import { AlertTriangle, CheckCircle, Info, X } from 'lucide-react';
import type { ExecutionMode } from '@/types/api';

const MODE_CONFIG: Record<ExecutionMode, { label: string; icon: React.ReactNode; badgeClass: string }> = {
  mock: {
    label: 'MOCK',
    icon: <AlertTriangle size={12} />,
    badgeClass: 'bg-mode-mock-bg text-mode-mock-text border-mode-mock-border',
  },
  live: {
    label: 'LIVE',
    icon: <CheckCircle size={12} />,
    badgeClass: 'bg-mode-live-bg text-mode-live-text border-mode-live-border animate-pulse-live',
  },
  mixed: {
    label: 'MIXED',
    icon: <Info size={12} />,
    badgeClass: 'bg-mode-mixed-bg text-mode-mixed-text border-mode-mixed-border',
  },
};

export function ModeIndicator(): JSX.Element {
  const { effectiveMode, serverModes, activeExecutions, isLiveMode } = useMode();
  const [showDetails, setShowDetails] = useState(false);

  const toggleDetails = useCallback(() => {
    setShowDetails((prev) => !prev);
  }, []);

  const config = MODE_CONFIG[effectiveMode];

  const serverModeEntries = Object.entries(serverModes);

  return (
    <div className="relative">
      <button
        onClick={toggleDetails}
        className={`mode-badge ${config.badgeClass} hover:opacity-80`}
        title={`Execution mode: ${effectiveMode.toUpperCase()}. Click for details.`}
      >
        {config.icon}
        <span>{config.label}</span>
        {isLiveMode && (
          <span className="ml-1 w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
        )}
      </button>

      {showDetails && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setShowDetails(false)} />
          <div className="absolute right-0 top-full mt-2 z-50 w-72 bg-white rounded-xl shadow-elevated border border-opsmate-200 p-4 animate-enter">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-opsmate-800">Execution Mode</h3>
              <button
                onClick={() => setShowDetails(false)}
                className="p-0.5 rounded-md hover:bg-opsmate-100 text-opsmate-400 hover:text-opsmate-600"
              >
                <X size={14} />
              </button>
            </div>

            <div className={`p-3 rounded-lg border mb-3 ${config.badgeClass}`}>
              <div className="flex items-center gap-2 font-medium">
                {config.icon}
                <span>Current Mode: {config.label}</span>
              </div>
              <p className="text-xs mt-1 opacity-80">
                {effectiveMode === 'mock' &&
                  'All tool calls are simulated. No real infrastructure changes.'}
                {effectiveMode === 'live' &&
                  'Tool calls execute against real infrastructure. Use with caution.'}
                {effectiveMode === 'mixed' &&
                  'Some servers use mock responses, others are live.'}
              </p>
            </div>

            {serverModeEntries.length > 0 && (
              <div className="mb-3">
                <h4 className="text-xs font-semibold text-opsmate-500 uppercase tracking-wider mb-2">
                  Per-Server Modes
                </h4>
                <div className="space-y-1">
                  {serverModeEntries.map(([server, mode]) => (
                    <div
                      key={server}
                      className="flex items-center justify-between text-xs py-1 px-2 rounded bg-opsmate-50"
                    >
                      <span className="font-mono text-opsmate-700">{server}</span>
                      <span
                        className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                          mode === 'live'
                            ? 'bg-green-100 text-green-700'
                            : mode === 'mock'
                            ? 'bg-amber-100 text-amber-700'
                            : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {mode}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="text-xs text-opsmate-500 border-t border-opsmate-100 pt-2">
              <div className="flex items-center justify-between">
                <span>Active executions:</span>
                <span className="font-semibold text-opsmate-700">{activeExecutions}</span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default ModeIndicator;
