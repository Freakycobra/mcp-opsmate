import React, { useState } from 'react';
import {
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  SkipForward,
  Server,
  Wrench,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  RotateCcw,
} from 'lucide-react';
import type { StepResult, StepStatus } from '@/types/api';

export interface StepCardProps {
  stepNumber: number;
  stepId: string;
  toolName: string;
  server: string;
  status: StepStatus;
  result?: StepResult;
  isCritical?: boolean;
}

const STATUS_CONFIG: Record<StepStatus, {
  icon: React.ReactNode;
  badgeClass: string;
  label: string;
}> = {
  pending: {
    icon: <Clock size={14} />,
    badgeClass: 'bg-opsmate-100 text-opsmate-600 border-opsmate-200',
    label: 'Pending',
  },
  running: {
    icon: <Loader2 size={14} className="animate-spin" />,
    badgeClass: 'bg-blue-50 text-blue-700 border-blue-200',
    label: 'Running',
  },
  completed: {
    icon: <CheckCircle2 size={14} />,
    badgeClass: 'bg-green-50 text-green-700 border-green-200',
    label: 'Completed',
  },
  failed: {
    icon: <XCircle size={14} />,
    badgeClass: 'bg-red-50 text-red-700 border-red-200',
    label: 'Failed',
  },
  skipped: {
    icon: <SkipForward size={14} />,
    badgeClass: 'bg-gray-50 text-gray-500 border-gray-200',
    label: 'Skipped',
  },
  skipped_due_to_dependency: {
    icon: <SkipForward size={14} />,
    badgeClass: 'bg-gray-50 text-gray-400 border-gray-200',
    label: 'Skipped (dep)',
  },
  retrying: {
    icon: <RotateCcw size={14} className="animate-spin" />,
    badgeClass: 'bg-amber-50 text-amber-700 border-amber-200',
    label: 'Retrying',
  },
};

export function StepCard({
  stepNumber,
  stepId,
  toolName,
  server,
  status,
  result,
  isCritical = false,
}: StepCardProps): JSX.Element {
  const [isExpanded, setIsExpanded] = useState(false);
  const config = STATUS_CONFIG[status];

  const duration = result?.duration_ms
    ? `${(result.duration_ms / 1000).toFixed(2)}s`
    : null;

  const hasOutput = result?.output && Object.keys(result.output).length > 0;
  const hasError = result?.error != null;

  return (
    <div
      className={`rounded-xl border bg-white transition-all ${
        isCritical
          ? 'border-red-200 shadow-sm'
          : 'border-opsmate-200 shadow-soft'
      } ${status === 'running' ? 'ring-1 ring-blue-200' : ''}`}
    >
      {/* Header - always visible */}
      <button
        onClick={() => setIsExpanded((prev) => !prev)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left"
      >
        {/* Step number */}
        <div
          className={`w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold shrink-0 ${
            status === 'completed'
              ? 'bg-green-100 text-green-700'
              : status === 'failed'
              ? 'bg-red-100 text-red-700'
              : status === 'running'
              ? 'bg-blue-100 text-blue-700'
              : 'bg-opsmate-100 text-opsmate-600'
          }`}
        >
          {stepNumber}
        </div>

        {/* Tool & Server */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <Wrench size={12} className="text-opsmate-400 shrink-0" />
            <span className="text-sm font-semibold text-opsmate-800 truncate">
              {toolName}
            </span>
            {isCritical && (
              <AlertTriangle size={12} className="text-red-400 shrink-0" title="Critical step" />
            )}
          </div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <Server size={10} className="text-opsmate-400" />
            <span className="text-2xs text-opsmate-500">{server}</span>
            <span className="text-2xs text-opsmate-300">|</span>
            <span className="text-2xs font-mono text-opsmate-400">{stepId}</span>
          </div>
        </div>

        {/* Status badge */}
        <span className={`status-badge ${config.badgeClass} shrink-0`}>
          {config.icon}
          <span>{config.label}</span>
        </span>

        {/* Duration */}
        {duration && (
          <span className="text-2xs font-mono text-opsmate-400 shrink-0 w-14 text-right">
            {duration}
          </span>
        )}

        {/* Expand toggle */}
        {(hasOutput || hasError) && (
          <span className="text-opsmate-400 shrink-0">
            {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </span>
        )}
      </button>

      {/* Expanded content */}
      {isExpanded && (hasOutput || hasError) && (
        <div className="px-4 pb-3 border-t border-opsmate-100 animate-enter">
          {hasOutput && (
            <div className="mt-3">
              <label className="text-2xs font-medium text-opsmate-400 uppercase tracking-wider">
                Output
              </label>
              <pre className="mt-1 p-3 bg-opsmate-50 rounded-lg text-2xs font-mono text-opsmate-700 overflow-x-auto max-h-64 overflow-y-auto border border-opsmate-100">
                {JSON.stringify(result?.output, null, 2)}
              </pre>
            </div>
          )}

          {hasError && (
            <div className="mt-3">
              <label className="text-2xs font-medium text-opsmate-400 uppercase tracking-wider">
                Error Details
              </label>
              <div className="mt-1 p-3 bg-red-50 rounded-lg border border-red-100">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-2xs font-semibold px-1.5 py-0.5 rounded bg-red-100 text-red-700">
                    {result?.error?.classification}
                  </span>
                  <span className="text-2xs text-red-400">
                    Attempt {result?.attempt_count}
                  </span>
                </div>
                <p className="text-xs text-red-700 leading-relaxed">
                  {result?.error?.message}
                </p>
                {result?.error?.retryable && (
                  <p className="text-2xs text-amber-600 mt-1 flex items-center gap-1">
                    <RotateCcw size={10} />
                    Will retry automatically
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default StepCard;
