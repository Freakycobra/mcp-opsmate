import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/context/AuthContext';
import { useMode } from '@/context/ModeContext';
import { useToast } from '@/components/Toast';
import { getHealth, setMode, listTools, refreshTools } from '@/api/admin';
import {
  Settings,
  Shield,
  ShieldAlert,
  CheckCircle2,
  XCircle,
  Loader2,
  AlertTriangle,
  RefreshCw,
  Server,
  Wrench,
  ChevronDown,
  ChevronUp,
  Wifi,
  WifiOff,
} from 'lucide-react';
import type { ExecutionMode, HealthResponse, ToolRegistryResponse } from '@/types/api';

export function AdminPage(): JSX.Element {
  const { isAdmin } = useAuth();
  const { mode: currentMode, refreshMode, serverModes } = useMode();
  const { showSuccess, showError } = useToast();

  const [selectedMode, setSelectedMode] = useState<ExecutionMode>('mock');
  const [modeReason, setModeReason] = useState('');
  const [isSwitching, setIsSwitching] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [tools, setTools] = useState<ToolRegistryResponse | null>(null);
  const [isLoadingHealth, setIsLoadingHealth] = useState(false);
  const [isLoadingTools, setIsLoadingTools] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [expandedServer, setExpandedServer] = useState<string | null>(null);

  // Fetch health and tools
  const fetchData = useCallback(async () => {
    setIsLoadingHealth(true);
    setIsLoadingTools(true);
    try {
      const [healthData, toolsData] = await Promise.all([
        getHealth(),
        listTools(),
      ]);
      setHealth(healthData);
      setTools(toolsData);
    } catch (err) {
      // Admin endpoints may fail if not admin
      console.warn('Admin data fetch failed:', err);
    } finally {
      setIsLoadingHealth(false);
      setIsLoadingTools(false);
    }
  }, []);

  useEffect(() => {
    if (isAdmin) {
      fetchData();
    }
  }, [isAdmin, fetchData]);

  // Sync selected mode with current mode
  useEffect(() => {
    setSelectedMode(currentMode);
  }, [currentMode]);

  const handleModeSwitch = useCallback(async () => {
    if (!modeReason.trim()) {
      showError('Reason Required', 'Please provide a reason for the mode change.');
      return;
    }

    if (selectedMode === currentMode) {
      showError('No Change', 'The selected mode is the same as the current mode.');
      return;
    }

    // Extra confirmation for LIVE mode
    if (selectedMode === 'live' && currentMode === 'mock') {
      const confirmed = window.confirm(
        'WARNING: You are about to switch from MOCK to LIVE mode. ' +
        'Tool calls will execute against REAL infrastructure.\n\n' +
        'Are you sure you want to continue?'
      );
      if (!confirmed) return;
    }

    setIsSwitching(true);
    try {
      await setMode(selectedMode, modeReason.trim());
      showSuccess(
        'Mode Switched',
        `Execution mode changed to ${selectedMode.toUpperCase()}.`
      );
      setModeReason('');
      refreshMode();
    } catch (err) {
      showError(
        'Mode Switch Failed',
        err instanceof Error ? err.message : 'Failed to switch mode'
      );
    } finally {
      setIsSwitching(false);
    }
  }, [selectedMode, currentMode, modeReason, showSuccess, showError, refreshMode]);

  const handleRefreshTools = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const result = await refreshTools();
      showSuccess(
        'Tools Refreshed',
        `Discovered ${result.tools_discovered} tools from ${result.servers_discovered} servers.`
      );
      // Reload tools list
      const toolsData = await listTools();
      setTools(toolsData);
    } catch (err) {
      showError(
        'Refresh Failed',
        err instanceof Error ? err.message : 'Failed to refresh tools'
      );
    } finally {
      setIsRefreshing(false);
    }
  }, [showSuccess, showError]);

  if (!isAdmin) {
    return (
      <div className="h-full flex items-center justify-center p-6">
        <div className="opsmate-card p-8 text-center max-w-md">
          <ShieldAlert size={32} className="text-opsmate-300 mx-auto mb-3" />
          <h2 className="text-lg font-semibold text-opsmate-800 mb-2">Admin Access Required</h2>
          <p className="text-sm text-opsmate-500 leading-relaxed">
            This page requires admin privileges. Please set your admin token in the authentication settings.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto scrollbar-thin p-6">
      <div className="mb-6">
        <h1 className="text-lg font-bold text-opsmate-900 flex items-center gap-2">
          <Settings size={20} className="text-opsmate-500" />
          Admin
        </h1>
        <p className="text-sm text-opsmate-500">
          System configuration and MCP server management
        </p>
      </div>

      <div className="max-w-4xl space-y-6">
        {/* Mode Switcher */}
        <div className="opsmate-card p-6">
          <div className="flex items-center gap-2 mb-4">
            <Shield size={16} className="text-opsmate-600" />
            <h2 className="text-sm font-semibold text-opsmate-800">Execution Mode</h2>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
            {(['mock', 'live', 'mixed'] as ExecutionMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setSelectedMode(m)}
                className={`p-3 rounded-xl border-2 text-left transition-all ${
                  selectedMode === m
                    ? m === 'mock'
                      ? 'border-amber-400 bg-amber-50'
                      : m === 'live'
                      ? 'border-green-400 bg-green-50'
                      : 'border-blue-400 bg-blue-50'
                    : 'border-opsmate-200 bg-white hover:border-opsmate-300'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`w-3 h-3 rounded-full ${
                      m === 'mock'
                        ? 'bg-amber-400'
                        : m === 'live'
                        ? 'bg-green-400'
                        : 'bg-blue-400'
                    } ${selectedMode === m ? 'ring-2 ring-offset-1 ring-opsmate-300' : ''}`}
                  />
                  <span className="text-sm font-bold uppercase text-opsmate-800">{m}</span>
                  {currentMode === m && (
                    <span className="text-2xs font-medium px-1.5 py-0.5 rounded-full bg-opsmate-800 text-white">
                      Active
                    </span>
                  )}
                </div>
                <p className="text-2xs text-opsmate-500 leading-relaxed">
                  {m === 'mock' && 'All tool calls return simulated responses. Safe for testing.'}
                  {m === 'live' && 'Tool calls execute against real infrastructure. Use with caution.'}
                  {m === 'mixed' && 'Per-server configuration determines mock vs live routing.'}
                </p>
              </button>
            ))}
          </div>

          {/* Reason input */}
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <label className="text-2xs font-medium text-opsmate-500 uppercase tracking-wider mb-1 block">
                Reason for Change (required)
              </label>
              <input
                type="text"
                value={modeReason}
                onChange={(e) => setModeReason(e.target.value)}
                placeholder="e.g., 'Testing deployment pipeline in live mode'"
                className="w-full text-sm bg-opsmate-50 border border-opsmate-200 rounded-lg px-3 py-2 text-opsmate-800 placeholder:text-opsmate-300 focus:outline-none focus:ring-1 focus:ring-opsmate-400"
              />
            </div>
            <button
              onClick={handleModeSwitch}
              disabled={isSwitching || !modeReason.trim() || selectedMode === currentMode}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                isSwitching || !modeReason.trim() || selectedMode === currentMode
                  ? 'bg-opsmate-200 text-opsmate-400 cursor-not-allowed'
                  : selectedMode === 'live'
                  ? 'bg-green-600 text-white hover:bg-green-700'
                  : 'bg-opsmate-800 text-white hover:bg-opsmate-700'
              }`}
            >
              {isSwitching ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                'Switch Mode'
              )}
            </button>
          </div>

          {/* Warning for LIVE */}
          {selectedMode === 'live' && currentMode !== 'live' && (
            <div className="mt-3 flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200">
              <AlertTriangle size={14} className="text-red-500 shrink-0 mt-0.5" />
              <p className="text-xs text-red-700 leading-relaxed">
                Switching to LIVE mode will cause all tool calls to execute against real infrastructure.
                This action requires explicit confirmation and will be logged to the audit trail.
              </p>
            </div>
          )}
        </div>

        {/* Server Health */}
        <div className="opsmate-card p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Server size={16} className="text-opsmate-600" />
              <h2 className="text-sm font-semibold text-opsmate-800">MCP Server Health</h2>
            </div>
            <button
              onClick={fetchData}
              disabled={isLoadingHealth}
              className="p-1.5 rounded-lg hover:bg-opsmate-100 text-opsmate-400 hover:text-opsmate-600 transition-colors"
            >
              <RefreshCw size={14} className={isLoadingHealth ? 'animate-spin' : ''} />
            </button>
          </div>

          {isLoadingHealth ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={20} className="animate-spin text-opsmate-400" />
            </div>
          ) : !health ? (
            <p className="text-sm text-opsmate-400 py-4 text-center">Health data unavailable</p>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center gap-2 mb-3">
                <span
                  className={`w-2 h-2 rounded-full ${
                    health.status === 'healthy'
                      ? 'bg-green-500'
                      : health.status === 'degraded'
                      ? 'bg-amber-500'
                      : 'bg-red-500'
                  }`}
                />
                <span className="text-sm font-medium text-opsmate-700 capitalize">
                  {health.status}
                </span>
                <span className="text-2xs text-opsmate-400">
                  v{health.version} · {Math.floor(health.uptime_seconds / 3600)}h uptime
                </span>
              </div>

              {Object.entries(health.checks).map(([name, check]) => (
                <div
                  key={name}
                  className="flex items-center justify-between py-2 px-3 rounded-lg bg-opsmate-50"
                >
                  <div className="flex items-center gap-2">
                    {check.status === 'ok' ? (
                      <Wifi size={12} className="text-green-500" />
                    ) : check.status === 'warning' ? (
                      <Wifi size={12} className="text-amber-500" />
                    ) : (
                      <WifiOff size={12} className="text-red-500" />
                    )}
                    <span className="text-xs text-opsmate-700">{name}</span>
                    {check.detail && (
                      <span className="text-2xs text-opsmate-400">{check.detail}</span>
                    )}
                  </div>
                  <span className="text-2xs font-mono text-opsmate-400">
                    {check.response_time_ms.toFixed(0)}ms
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Tool Registry */}
        <div className="opsmate-card p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Wrench size={16} className="text-opsmate-600" />
              <h2 className="text-sm font-semibold text-opsmate-800">Tool Registry</h2>
            </div>
            <button
              onClick={handleRefreshTools}
              disabled={isRefreshing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-opsmate-100 text-opsmate-700 hover:bg-opsmate-200 transition-colors disabled:opacity-50"
            >
              <RefreshCw size={12} className={isRefreshing ? 'animate-spin' : ''} />
              Refresh
            </button>
          </div>

          {isLoadingTools ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={20} className="animate-spin text-opsmate-400" />
            </div>
          ) : !tools ? (
            <p className="text-sm text-opsmate-400 py-4 text-center">Tool data unavailable</p>
          ) : (
            <div>
              <div className="flex items-center gap-4 mb-4 text-2xs text-opsmate-500">
                <span>{tools.server_count} servers</span>
                <span>{tools.total_tools} tools</span>
                <span>
                  Last refreshed: {new Date(tools.last_refreshed_at).toLocaleString()}
                </span>
              </div>

              <div className="space-y-2">
                {tools.servers.map((server) => (
                  <div key={server.server_name} className="border border-opsmate-200 rounded-lg">
                    <button
                      onClick={() =>
                        setExpandedServer((prev) =>
                          prev === server.server_name ? null : server.server_name
                        )
                      }
                      className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-opsmate-50 transition-colors"
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className={`w-2 h-2 rounded-full ${
                            server.connected ? 'bg-green-500' : 'bg-red-500'
                          }`}
                        />
                        <span className="text-xs font-semibold text-opsmate-700">
                          {server.server_name}
                        </span>
                        <span className="text-2xs text-opsmate-400">({server.transport})</span>
                        <span
                          className={`text-2xs font-medium px-1.5 py-0.5 rounded ${
                            server.mode === 'live'
                              ? 'bg-green-100 text-green-700'
                              : server.mode === 'mock'
                              ? 'bg-amber-100 text-amber-700'
                              : 'bg-gray-100 text-gray-600'
                          }`}
                        >
                          {server.mode}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-2xs text-opsmate-400">
                          {server.tool_count} tools
                        </span>
                        {expandedServer === server.server_name ? (
                          <ChevronUp size={12} className="text-opsmate-400" />
                        ) : (
                          <ChevronDown size={12} className="text-opsmate-400" />
                        )}
                      </div>
                    </button>

                    {expandedServer === server.server_name && (
                      <div className="px-3 pb-3 border-t border-opsmate-100 animate-enter">
                        <div className="mt-2 space-y-1">
                          {server.tools.map((tool) => (
                            <div
                              key={tool.name}
                              className="flex items-start gap-2 py-1.5 px-2 rounded hover:bg-opsmate-50"
                            >
                              <Wrench size={10} className="text-opsmate-400 mt-0.5 shrink-0" />
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="text-xs font-mono text-opsmate-700">
                                    {tool.name}
                                  </span>
                                  {tool.destructive && (
                                    <span className="text-2xs px-1 py-0.5 rounded bg-red-100 text-red-600 font-medium">
                                      destructive
                                    </span>
                                  )}
                                </div>
                                <p className="text-2xs text-opsmate-500 leading-relaxed">
                                  {tool.description}
                                </p>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default AdminPage;
