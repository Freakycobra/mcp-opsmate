import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { listExecutions } from '@/api/executions';
import {
  Clock,
  ChevronLeft,
  ChevronRight,
  Filter,
  Search,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock4,
  AlertTriangle,
  Ban,
  Eye,
} from 'lucide-react';
import type { ExecutionSummary, ExecutionStatus, ExecutionMode } from '@/types/api';

const STATUS_ICONS: Record<ExecutionStatus, React.ReactNode> = {
  pending: <Clock size={14} className="text-opsmate-400" />,
  planning: <Loader2 size={14} className="text-blue-400 animate-spin" />,
  awaiting_confirmation: <AlertTriangle size={14} className="text-amber-500" />,
  executing: <Loader2 size={14} className="text-blue-500 animate-spin" />,
  paused: <Clock4 size={14} className="text-amber-400" />,
  completed: <CheckCircle2 size={14} className="text-green-500" />,
  failed: <XCircle size={14} className="text-red-500" />,
  cancelled: <Ban size={14} className="text-opsmate-400" />,
};

const STATUS_BADGES: Record<ExecutionStatus, string> = {
  pending: 'bg-opsmate-100 text-opsmate-600 border-opsmate-200',
  planning: 'bg-blue-50 text-blue-600 border-blue-200',
  awaiting_confirmation: 'bg-amber-50 text-amber-700 border-amber-200',
  executing: 'bg-blue-50 text-blue-700 border-blue-200',
  paused: 'bg-amber-50 text-amber-600 border-amber-200',
  completed: 'bg-green-50 text-green-700 border-green-200',
  failed: 'bg-red-50 text-red-700 border-red-200',
  cancelled: 'bg-gray-50 text-gray-500 border-gray-200',
};

export function ExecutionHistory(): JSX.Element {
  const navigate = useNavigate();
  const [executions, setExecutions] = useState<ExecutionSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [statusFilter, setStatusFilter] = useState<ExecutionStatus | ''>('');
  const [modeFilter, setModeFilter] = useState<ExecutionMode | ''>('');
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const totalPages = Math.ceil(total / pageSize);

  const fetchExecutions = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listExecutions({
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
        mode: modeFilter || undefined,
        command_q: searchQuery || undefined,
        sort: '-created_at',
      });
      setExecutions(response.items);
      setTotal(response.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch executions');
    } finally {
      setIsLoading(false);
    }
  }, [page, pageSize, statusFilter, modeFilter, searchQuery]);

  useEffect(() => {
    fetchExecutions();
  }, [fetchExecutions]);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
  }, [statusFilter, modeFilter, searchQuery]);

  const formatDuration = (ms: number | null): string => {
    if (!ms) return '-';
    if (ms < 1000) return `${ms.toFixed(0)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const formatDate = (iso: string): string => {
    const d = new Date(iso);
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="opsmate-card overflow-hidden">
      {/* Filters */}
      <div className="px-4 py-3 border-b border-opsmate-200 flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5 text-sm font-medium text-opsmate-600">
          <Filter size={14} />
          <span>Filters</span>
        </div>

        {/* Status filter */}
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as ExecutionStatus | '')}
          className="text-xs bg-opsmate-50 border border-opsmate-200 rounded-lg px-2.5 py-1.5 text-opsmate-700 focus:outline-none focus:ring-1 focus:ring-opsmate-400"
        >
          <option value="">All Statuses</option>
          <option value="pending">Pending</option>
          <option value="planning">Planning</option>
          <option value="awaiting_confirmation">Awaiting Confirmation</option>
          <option value="executing">Executing</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
        </select>

        {/* Mode filter */}
        <select
          value={modeFilter}
          onChange={(e) => setModeFilter(e.target.value as ExecutionMode | '')}
          className="text-xs bg-opsmate-50 border border-opsmate-200 rounded-lg px-2.5 py-1.5 text-opsmate-700 focus:outline-none focus:ring-1 focus:ring-opsmate-400"
        >
          <option value="">All Modes</option>
          <option value="mock">Mock</option>
          <option value="live">Live</option>
          <option value="mixed">Mixed</option>
        </select>

        {/* Search */}
        <div className="relative ml-auto">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-opsmate-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search commands..."
            className="pl-8 pr-3 py-1.5 text-xs bg-opsmate-50 border border-opsmate-200 rounded-lg text-opsmate-700 placeholder:text-opsmate-400 focus:outline-none focus:ring-1 focus:ring-opsmate-400 w-48"
          />
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-opsmate-50 border-b border-opsmate-200">
              <th className="text-left px-4 py-2.5 font-semibold text-opsmate-500 uppercase tracking-wider">
                ID
              </th>
              <th className="text-left px-4 py-2.5 font-semibold text-opsmate-500 uppercase tracking-wider">
                Command
              </th>
              <th className="text-left px-4 py-2.5 font-semibold text-opsmate-500 uppercase tracking-wider">
                Status
              </th>
              <th className="text-left px-4 py-2.5 font-semibold text-opsmate-500 uppercase tracking-wider">
                Mode
              </th>
              <th className="text-left px-4 py-2.5 font-semibold text-opsmate-500 uppercase tracking-wider">
                Steps
              </th>
              <th className="text-left px-4 py-2.5 font-semibold text-opsmate-500 uppercase tracking-wider">
                Duration
              </th>
              <th className="text-left px-4 py-2.5 font-semibold text-opsmate-500 uppercase tracking-wider">
                Date
              </th>
              <th className="px-4 py-2.5"></th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center text-opsmate-400">
                  <Loader2 size={20} className="animate-spin mx-auto mb-2" />
                  <span>Loading executions...</span>
                </td>
              </tr>
            ) : error ? (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center text-red-500">
                  <XCircle size={20} className="mx-auto mb-2" />
                  <span>{error}</span>
                </td>
              </tr>
            ) : executions.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center text-opsmate-400">
                  <Clock size={20} className="mx-auto mb-2 text-opsmate-300" />
                  <p>No executions found</p>
                  {statusFilter || modeFilter || searchQuery ? (
                    <p className="text-2xs mt-1">Try adjusting your filters</p>
                  ) : null}
                </td>
              </tr>
            ) : (
              executions.map((execution) => (
                <tr
                  key={execution.execution_id}
                  className="border-b border-opsmate-100 hover:bg-opsmate-50/50 transition-colors cursor-pointer"
                  onClick={() => navigate(`/history?detail=${execution.execution_id}`)}
                >
                  <td className="px-4 py-3">
                    <span className="font-mono text-opsmate-500">
                      {execution.execution_id.slice(0, 8)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-opsmate-800 font-medium truncate max-w-xs block" title={execution.command_text}>
                      {execution.command_text}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-2xs font-medium border ${STATUS_BADGES[execution.status]}`}>
                      {STATUS_ICONS[execution.status]}
                      <span className="capitalize">{execution.status.replace(/_/g, ' ')}</span>
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-2xs font-semibold uppercase px-1.5 py-0.5 rounded ${
                      execution.execution_mode === 'live'
                        ? 'bg-green-100 text-green-700'
                        : execution.execution_mode === 'mock'
                        ? 'bg-amber-100 text-amber-700'
                        : 'bg-blue-100 text-blue-700'
                    }`}>
                      {execution.execution_mode}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-opsmate-600">
                      {execution.step_count}
                      {execution.failed_steps > 0 && (
                        <span className="text-red-500 ml-1">
                          ({execution.failed_steps} failed)
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-opsmate-500">
                    {formatDuration(execution.total_duration_ms)}
                  </td>
                  <td className="px-4 py-3 text-opsmate-500">
                    {formatDate(execution.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        navigate(`/history?detail=${execution.execution_id}`);
                      }}
                      className="p-1 rounded hover:bg-opsmate-100 text-opsmate-400 hover:text-opsmate-600"
                    >
                      <Eye size={14} />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="px-4 py-3 border-t border-opsmate-200 flex items-center justify-between">
          <span className="text-2xs text-opsmate-400">
            Showing {(page - 1) * pageSize + 1} - {Math.min(page * pageSize, total)} of {total}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="p-1.5 rounded-lg hover:bg-opsmate-100 disabled:opacity-30 disabled:cursor-not-allowed text-opsmate-600"
            >
              <ChevronLeft size={14} />
            </button>
            <span className="text-xs text-opsmate-600 px-2">
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="p-1.5 rounded-lg hover:bg-opsmate-100 disabled:opacity-30 disabled:cursor-not-allowed text-opsmate-600"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default ExecutionHistory;
