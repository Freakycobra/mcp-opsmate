import React, { useState, useEffect, useCallback } from 'react';
import { listExecutions } from '@/api/executions';
import { getHealth } from '@/api/admin';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import {
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  TrendingUp,
  Server,
  Loader2,
  AlertTriangle,
} from 'lucide-react';
import type { ExecutionSummary } from '@/types/api';

// ─── Types ─────────────────────────────────────────────────────────

interface HourlyData {
  hour: string;
  executions: number;
  completed: number;
  failed: number;
}

interface ServerUsage {
  name: string;
  count: number;
  color: string;
}

interface Stats {
  total24h: number;
  total7d: number;
  total30d: number;
  successRate: number;
  avgDuration: number;
  activeNow: number;
}

// ─── Colors for charts ─────────────────────────────────────────────

const CHART_COLORS = [
  '#9c8878',
  '#7d6c5e',
  '#b8a898',
  '#d4c8b8',
  '#5e5046',
  '#3d342e',
  '#4a7ec7',
  '#4a8c5c',
];

// ─── Helper functions ──────────────────────────────────────────────

function getHoursAgo(hours: number): string {
  const d = new Date();
  d.setHours(d.getHours() - hours);
  return d.toISOString();
}

function getDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

function formatHourLabel(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('en-US', { hour: 'numeric', hour12: true });
}

// ─── Stat Card ─────────────────────────────────────────────────────

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ReactNode;
  accentColor: string;
}

function StatCard({ title, value, subtitle, icon, accentColor }: StatCardProps): JSX.Element {
  return (
    <div className="opsmate-card p-4">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <p className="text-2xs font-medium text-opsmate-400 uppercase tracking-wider">{title}</p>
          <p className="text-2xl font-bold text-opsmate-900 mt-1">{value}</p>
          {subtitle && <p className="text-2xs text-opsmate-500 mt-1">{subtitle}</p>}
        </div>
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center"
          style={{ backgroundColor: `${accentColor}15` }}
        >
          <span style={{ color: accentColor }}>{icon}</span>
        </div>
      </div>
    </div>
  );
}

// ─── Main Dashboard Component ──────────────────────────────────────

export function Dashboard(): JSX.Element {
  const [executions, setExecutions] = useState<ExecutionSummary[]>([]);
  const [stats, setStats] = useState<Stats>({
    total24h: 0,
    total7d: 0,
    total30d: 0,
    successRate: 0,
    avgDuration: 0,
    activeNow: 0,
  });
  const [hourlyData, setHourlyData] = useState<HourlyData[]>([]);
  const [serverUsage, setServerUsage] = useState<ServerUsage[]>([]);
  const [healthStatus, setHealthStatus] = useState<Record<string, { status: string; response_time_ms: number }>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      // Fetch executions for different time windows
      const [execs24h, execs7d, execs30d] = await Promise.all([
        listExecutions({ from_date: getHoursAgo(24), page_size: 100, sort: '-created_at' }),
        listExecutions({ from_date: getDaysAgo(7), page_size: 100, sort: '-created_at' }),
        listExecutions({ from_date: getDaysAgo(30), page_size: 100, sort: '-created_at' }),
      ]);

      const all24h = execs24h.items;
      const all30d = execs30d.items;

      // Calculate stats
      const completed24h = all24h.filter((e) => e.status === 'completed');
      const failed24h = all24h.filter((e) => e.status === 'failed');
      const successRate = all24h.length > 0
        ? Math.round((completed24h.length / all24h.length) * 100)
        : 0;

      const durations = all24h
        .filter((e) => e.total_duration_ms != null)
        .map((e) => e.total_duration_ms!);
      const avgDuration = durations.length > 0
        ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length)
        : 0;

      const activeNow = all24h.filter(
        (e) => e.status === 'executing' || e.status === 'planning'
      ).length;

      setStats({
        total24h: execs24h.total,
        total7d: execs7d.total,
        total30d: execs30d.total,
        successRate,
        avgDuration,
        activeNow,
      });

      setExecutions(all24h.slice(0, 10));

      // Build hourly chart data (last 24 hours)
      const hours: HourlyData[] = [];
      const now = new Date();
      for (let i = 23; i >= 0; i--) {
        const hourStart = new Date(now);
        hourStart.setHours(hourStart.getHours() - i);
        hourStart.setMinutes(0, 0, 0);
        const hourEnd = new Date(hourStart);
        hourEnd.setHours(hourEnd.getHours() + 1);

        const hourExecs = all24h.filter((e) => {
          const d = new Date(e.created_at);
          return d >= hourStart && d < hourEnd;
        });

        hours.push({
          hour: formatHourLabel(hourStart.toISOString()),
          executions: hourExecs.length,
          completed: hourExecs.filter((e) => e.status === 'completed').length,
          failed: hourExecs.filter((e) => e.status === 'failed').length,
        });
      }
      setHourlyData(hours);

      // Mock server usage (would come from real data in production)
      setServerUsage([
        { name: 'aws-ecs', count: Math.round(all30d.length * 0.3), color: CHART_COLORS[0] },
        { name: 'postgres-db', count: Math.round(all30d.length * 0.25), color: CHART_COLORS[1] },
        { name: 'github', count: Math.round(all30d.length * 0.2), color: CHART_COLORS[2] },
        { name: 'tavily-search', count: Math.round(all30d.length * 0.15), color: CHART_COLORS[3] },
        { name: 'slack', count: Math.round(all30d.length * 0.1), color: CHART_COLORS[4] },
      ]);

      // Health check
      try {
        const health = await getHealth();
        setHealthStatus(health.checks);
      } catch {
        // Health endpoint may not be available
        setHealthStatus({});
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch dashboard data');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000); // Auto-refresh every 60s
    return () => clearInterval(interval);
  }, [fetchData]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={24} className="animate-spin text-opsmate-400" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="opsmate-card p-8 text-center">
        <AlertTriangle size={24} className="text-red-400 mx-auto mb-2" />
        <p className="text-sm text-red-600">{error}</p>
        <button
          onClick={fetchData}
          className="mt-3 text-xs text-opsmate-500 hover:text-opsmate-700 underline"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="24h Executions"
          value={stats.total24h}
          subtitle={`${stats.total7d} this week`}
          icon={<Activity size={18} />}
          accentColor="#9c8878"
        />
        <StatCard
          title="Success Rate"
          value={`${stats.successRate}%`}
          subtitle="Last 24 hours"
          icon={<TrendingUp size={18} />}
          accentColor="#4a8c5c"
        />
        <StatCard
          title="Avg Duration"
          value={stats.avgDuration < 1000 ? `${stats.avgDuration}ms` : `${(stats.avgDuration / 1000).toFixed(1)}s`}
          subtitle="Last 24 hours"
          icon={<Clock size={18} />}
          accentColor="#4a7ec7"
        />
        <StatCard
          title="Active Now"
          value={stats.activeNow}
          subtitle="Currently executing"
          icon={<Server size={18} />}
          accentColor="#b08d2b"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Hourly executions bar chart */}
        <div className="lg:col-span-2 opsmate-card p-4">
          <h3 className="text-sm font-semibold text-opsmate-800 mb-4">
            Executions by Hour (Last 24h)
          </h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={hourlyData} barGap={1}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e8e0d4" vertical={false} />
                <XAxis
                  dataKey="hour"
                  tick={{ fontSize: 10, fill: '#9c8878' }}
                  tickLine={false}
                  axisLine={{ stroke: '#d4c8b8' }}
                  interval={2}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: '#9c8878' }}
                  tickLine={false}
                  axisLine={false}
                  allowDecimals={false}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#fff',
                    border: '1px solid #e8e0d4',
                    borderRadius: '8px',
                    fontSize: '12px',
                    boxShadow: '0 2px 8px rgba(30, 26, 23, 0.06)',
                  }}
                />
                <Bar dataKey="executions" fill="#9c8878" radius={[3, 3, 0, 0]} name="Total" />
                <Bar dataKey="completed" fill="#a8d8b8" radius={[3, 3, 0, 0]} name="Completed" />
                <Bar dataKey="failed" fill="#f0a8a0" radius={[3, 3, 0, 0]} name="Failed" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Server usage pie chart */}
        <div className="opsmate-card p-4">
          <h3 className="text-sm font-semibold text-opsmate-800 mb-4">
            MCP Server Usage (30d)
          </h3>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={serverUsage}
                  cx="50%"
                  cy="50%"
                  innerRadius={45}
                  outerRadius={70}
                  paddingAngle={3}
                  dataKey="count"
                >
                  {serverUsage.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#fff',
                    border: '1px solid #e8e0d4',
                    borderRadius: '8px',
                    fontSize: '12px',
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 space-y-1">
            {serverUsage.map((server) => (
              <div key={server.name} className="flex items-center justify-between text-2xs">
                <div className="flex items-center gap-1.5">
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: server.color }}
                  />
                  <span className="text-opsmate-600">{server.name}</span>
                </div>
                <span className="text-opsmate-400">{server.count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Health Status + Recent Executions */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* MCP Server Health */}
        <div className="opsmate-card p-4">
          <h3 className="text-sm font-semibold text-opsmate-800 mb-3">
            MCP Server Health
          </h3>
          {Object.keys(healthStatus).length === 0 ? (
            <p className="text-2xs text-opsmate-400 py-4 text-center">Health data unavailable</p>
          ) : (
            <div className="space-y-2">
              {Object.entries(healthStatus).map(([name, check]) => (
                <div
                  key={name}
                  className="flex items-center justify-between py-1.5 px-2 rounded-lg bg-opsmate-50"
                >
                  <div className="flex items-center gap-2">
                    {check.status === 'ok' ? (
                      <CheckCircle2 size={12} className="text-green-500" />
                    ) : check.status === 'warning' ? (
                      <AlertTriangle size={12} className="text-amber-500" />
                    ) : (
                      <XCircle size={12} className="text-red-500" />
                    )}
                    <span className="text-xs text-opsmate-700">{name}</span>
                  </div>
                  <span className="text-2xs font-mono text-opsmate-400">
                    {check.response_time_ms.toFixed(0)}ms
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Recent Executions */}
        <div className="lg:col-span-2 opsmate-card p-4">
          <h3 className="text-sm font-semibold text-opsmate-800 mb-3">
            Recent Executions
          </h3>
          <div className="space-y-2">
            {executions.length === 0 ? (
              <p className="text-2xs text-opsmate-400 py-4 text-center">No recent executions</p>
            ) : (
              executions.slice(0, 8).map((execution) => (
                <div
                  key={execution.execution_id}
                  className="flex items-center gap-3 py-2 px-3 rounded-lg hover:bg-opsmate-50 transition-colors"
                >
                  <span className="shrink-0">
                    {execution.status === 'completed' ? (
                      <CheckCircle2 size={14} className="text-green-500" />
                    ) : execution.status === 'failed' ? (
                      <XCircle size={14} className="text-red-500" />
                    ) : (
                      <Loader2 size={14} className="text-blue-400 animate-spin" />
                    )}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-opsmate-800 truncate" title={execution.command_text}>
                      {execution.command_text}
                    </p>
                    <p className="text-2xs text-opsmate-400">
                      {execution.step_count} steps
                      {execution.total_duration_ms && (
                        <span> · {(execution.total_duration_ms / 1000).toFixed(1)}s</span>
                      )}
                    </p>
                  </div>
                  <span className={`text-2xs font-semibold uppercase px-1.5 py-0.5 rounded ${
                    execution.execution_mode === 'live'
                      ? 'bg-green-100 text-green-700'
                      : execution.execution_mode === 'mock'
                      ? 'bg-amber-100 text-amber-700'
                      : 'bg-blue-100 text-blue-700'
                  }`}>
                    {execution.execution_mode}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;
