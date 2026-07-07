import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ExecutionHistory } from '@/components/ExecutionHistory';
import { getExecution } from '@/api/executions';
import { StepCard } from '@/components/StepCard';
import {
  ArrowLeft,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  AlertTriangle,
  Ban,
  Server,
  Calendar,
  Clock3,
  Wrench,
} from 'lucide-react';
import type { ExecutionDetail, ExecutionStatus } from '@/types/api';

const STATUS_CONFIG: Record<ExecutionStatus, {
  icon: React.ReactNode;
  badgeClass: string;
  label: string;
}> = {
  pending: {
    icon: <Clock size={16} />,
    badgeClass: 'bg-opsmate-100 text-opsmate-600 border-opsmate-200',
    label: 'Pending',
  },
  planning: {
    icon: <Loader2 size={16} className="animate-spin" />,
    badgeClass: 'bg-blue-50 text-blue-600 border-blue-200',
    label: 'Planning',
  },
  awaiting_confirmation: {
    icon: <AlertTriangle size={16} />,
    badgeClass: 'bg-amber-50 text-amber-700 border-amber-200',
    label: 'Awaiting Confirmation',
  },
  executing: {
    icon: <Loader2 size={16} className="animate-spin" />,
    badgeClass: 'bg-blue-50 text-blue-700 border-blue-200',
    label: 'Executing',
  },
  paused: {
    icon: <Clock size={16} />,
    badgeClass: 'bg-amber-50 text-amber-600 border-amber-200',
    label: 'Paused',
  },
  completed: {
    icon: <CheckCircle2 size={16} />,
    badgeClass: 'bg-green-50 text-green-700 border-green-200',
    label: 'Completed',
  },
  failed: {
    icon: <XCircle size={16} />,
    badgeClass: 'bg-red-50 text-red-700 border-red-200',
    label: 'Failed',
  },
  cancelled: {
    icon: <Ban size={16} />,
    badgeClass: 'bg-gray-50 text-gray-500 border-gray-200',
    label: 'Cancelled',
  },
};

export function HistoryPage(): JSX.Element {
  const [searchParams, setSearchParams] = useSearchParams();
  const detailId = searchParams.get('detail');

  const [detail, setDetail] = useState<ExecutionDetail | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!detailId) {
      setDetail(null);
      return;
    }

    setIsLoading(true);
    setError(null);
    getExecution(detailId)
      .then((data) => {
        setDetail(data);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load execution details');
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [detailId]);

  const handleBack = () => {
    setSearchParams({});
  };

  const formatDate = (iso: string | null): string => {
    if (!iso) return '-';
    return new Date(iso).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const formatDuration = (ms: number | null): string => {
    if (!ms) return '-';
    if (ms < 1000) return `${ms.toFixed(0)}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  };

  // Detail view
  if (detailId) {
    return (
      <div className="h-full overflow-y-auto scrollbar-thin p-6">
        {/* Back button */}
        <button
          onClick={handleBack}
          className="flex items-center gap-1.5 text-sm text-opsmate-500 hover:text-opsmate-700 transition-colors mb-4"
        >
          <ArrowLeft size={16} />
          Back to History
        </button>

        {isLoading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 size={24} className="animate-spin text-opsmate-400" />
          </div>
        ) : error ? (
          <div className="opsmate-card p-8 text-center">
            <XCircle size={24} className="text-red-400 mx-auto mb-2" />
            <p className="text-sm text-red-600">{error}</p>
          </div>
        ) : detail ? (
          <div className="space-y-6 max-w-4xl">
            {/* Header */}
            <div className="opsmate-card p-6">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium border ${STATUS_CONFIG[detail.status].badgeClass}`}>
                      {STATUS_CONFIG[detail.status].icon}
                      {STATUS_CONFIG[detail.status].label}
                    </span>
                    <span className={`text-2xs font-semibold uppercase px-1.5 py-0.5 rounded ${
                      detail.execution_mode === 'live'
                        ? 'bg-green-100 text-green-700'
                        : detail.execution_mode === 'mock'
                        ? 'bg-amber-100 text-amber-700'
                        : 'bg-blue-100 text-blue-700'
                    }`}>
                      {detail.execution_mode}
                    </span>
                  </div>
                  <h1 className="text-lg font-bold text-opsmate-900 mb-1">
                    {detail.command_text}
                  </h1>
                  <p className="text-2xs font-mono text-opsmate-400">
                    {detail.execution_id}
                  </p>
                </div>
              </div>

              {/* Metadata grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-4 pt-4 border-t border-opsmate-100">
                <div>
                  <div className="flex items-center gap-1 text-2xs text-opsmate-400 mb-0.5">
                    <Calendar size={10} />
                    <span>Created</span>
                  </div>
                  <p className="text-xs text-opsmate-700">{formatDate(detail.created_at)}</p>
                </div>
                <div>
                  <div className="flex items-center gap-1 text-2xs text-opsmate-400 mb-0.5">
                    <CheckCircle2 size={10} />
                    <span>Completed</span>
                  </div>
                  <p className="text-xs text-opsmate-700">{formatDate(detail.completed_at)}</p>
                </div>
                <div>
                  <div className="flex items-center gap-1 text-2xs text-opsmate-400 mb-0.5">
                    <Clock3 size={10} />
                    <span>Planning</span>
                  </div>
                  <p className="text-xs font-mono text-opsmate-700">
                    {formatDuration(detail.planning_duration_ms)}
                  </p>
                </div>
                <div>
                  <div className="flex items-center gap-1 text-2xs text-opsmate-400 mb-0.5">
                    <Clock size={10} />
                    <span>Total Duration</span>
                  </div>
                  <p className="text-xs font-mono text-opsmate-700">
                    {formatDuration(detail.total_duration_ms)}
                  </p>
                </div>
              </div>
            </div>

            {/* Steps */}
            {detail.plan && (
              <div className="space-y-3">
                <h2 className="text-sm font-semibold text-opsmate-800 flex items-center gap-2">
                  <Wrench size={14} />
                  Execution Steps ({detail.plan.steps.length})
                </h2>
                {detail.plan.steps.map((step, index) => (
                  <StepCard
                    key={step.id}
                    stepNumber={index + 1}
                    stepId={step.id}
                    toolName={step.tool_name}
                    server={step.server}
                    status={detail.results[step.id]?.status ?? 'pending'}
                    result={detail.results[step.id] ?? undefined}
                    isCritical={step.critical}
                  />
                ))}
              </div>
            )}

            {/* Results summary */}
            {Object.keys(detail.results).length > 0 && (
              <div className="opsmate-card p-4">
                <h2 className="text-sm font-semibold text-opsmate-800 mb-3">Results Summary</h2>
                <div className="space-y-2">
                  {Object.entries(detail.results).map(([stepId, result]) => (
                    <div
                      key={stepId}
                      className="flex items-center gap-3 p-2 rounded-lg bg-opsmate-50"
                    >
                      {result.status === 'completed' ? (
                        <CheckCircle2 size={14} className="text-green-500 shrink-0" />
                      ) : result.status === 'failed' ? (
                        <XCircle size={14} className="text-red-500 shrink-0" />
                      ) : (
                        <Clock size={14} className="text-opsmate-400 shrink-0" />
                      )}
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-opsmate-700">
                          {result.tool_name}
                        </p>
                        <p className="text-2xs text-opsmate-400">{stepId}</p>
                      </div>
                      {result.output && (
                        <pre className="text-2xs font-mono text-opsmate-500 bg-white px-2 py-1 rounded max-w-xs truncate">
                          {JSON.stringify(result.output).slice(0, 80)}...
                        </pre>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Audit Log */}
            {detail.audit_log.length > 0 && (
              <div className="opsmate-card p-4">
                <h2 className="text-sm font-semibold text-opsmate-800 mb-3">Audit Log</h2>
                <div className="space-y-1 max-h-64 overflow-y-auto scrollbar-thin">
                  {detail.audit_log.map((entry) => (
                    <div
                      key={entry.id}
                      className="flex items-center gap-3 py-1.5 px-2 rounded hover:bg-opsmate-50"
                    >
                      <span className="text-2xs text-opsmate-400 w-28 shrink-0">
                        {formatDate(entry.timestamp)}
                      </span>
                      <span className="text-2xs font-medium text-opsmate-600 px-1.5 py-0.5 rounded bg-opsmate-100">
                        {entry.action}
                      </span>
                      <span className="text-2xs text-opsmate-500">
                        {entry.user_id || 'system'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : null}
      </div>
    );
  }

  // List view
  return (
    <div className="h-full overflow-y-auto scrollbar-thin p-6">
      <div className="mb-4">
        <h1 className="text-lg font-bold text-opsmate-900">Execution History</h1>
        <p className="text-sm text-opsmate-500">Browse and inspect past command executions</p>
      </div>
      <ExecutionHistory />
    </div>
  );
}

export default HistoryPage;
