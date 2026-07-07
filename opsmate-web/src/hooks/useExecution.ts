import { useState, useCallback, useRef, useEffect } from 'react';
import { submitCommand, getStreamUrl } from '@/api/commands';
import { approveExecution, rejectExecution } from '@/api/executions';
import { useSSE } from './useSSE';
import type {
  CommandResponse,
  SSEEvent,
  ExecutionPlan,
  ExecutionStatus,
  StepStatus,
  StepResult,
} from '@/types/api';

export interface ExecutionState {
  executionId: string | null;
  commandText: string;
  status: ExecutionStatus;
  plan: ExecutionPlan | null;
  stepResults: Record<string, StepResult>;
  stepStatuses: Record<string, StepStatus>;
  riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | null;
  summary: string | null;
  resultPreview: Record<string, unknown> | null;
  totalDurationMs: number | null;
  error: string | null;
  escalation: {
    stepId: string;
    reason: string;
    options: string[];
    timeoutSeconds: number;
    impact: string;
  } | null;
}

export interface UseExecutionReturn {
  /** Current execution state */
  state: ExecutionState;
  /** Whether a command is being submitted or executing */
  isLoading: boolean;
  /** Connection status for SSE */
  isConnected: boolean;
  /** Error from API or SSE */
  error: string | null;
  /** Submit a new command */
  submit: (text: string, options?: { autoApprove?: boolean; modeOverride?: 'mock' | 'live' | 'mixed' }) => Promise<void>;
  /** Approve the current pending plan */
  approve: () => Promise<void>;
  /** Reject the current pending plan */
  reject: (reason?: string) => Promise<void>;
  /** Reset to initial state */
  reset: () => void;
  /** Raw SSE events for debugging */
  events: SSEEvent[];
}

const initialState: ExecutionState = {
  executionId: null,
  commandText: '',
  status: 'pending',
  plan: null,
  stepResults: {},
  stepStatuses: {},
  riskLevel: null,
  summary: null,
  resultPreview: null,
  totalDurationMs: null,
  error: null,
  escalation: null,
};

/**
 * Hook that manages the full execution lifecycle:
 * - Submit command → receive execution ID
 * - Connect to SSE stream
 * - Handle plan generation & confirmation
 * - Track step progress
 * - Handle escalations
 */
export function useExecution(): UseExecutionReturn {
  const [state, setState] = useState<ExecutionState>(initialState);
  const [isLoading, setIsLoading] = useState(false);
  const [streamUrl, setStreamUrl] = useState<string | null>(null);
  const [commandResponse, setCommandResponse] = useState<CommandResponse | null>(null);

  const currentExecutionIdRef = useRef<string | null>(null);

  const { events, isConnected, error: sseError, disconnect } = useSSE({
    url: streamUrl,
    autoReconnect: true,
    reconnectDelay: 3000,
    maxReconnects: 10,
  });

  // Process SSE events to update execution state
  useEffect(() => {
    if (events.length === 0) return;

    const latestEvent = events[events.length - 1];

    setState((prev) => {
      const next = { ...prev };

      switch (latestEvent.type) {
        case 'execution.created': {
          next.status = latestEvent.payload.status;
          next.executionId = latestEvent.payload.execution_id;
          break;
        }

        case 'plan.generated': {
          next.plan = latestEvent.payload;
          // Initialize step statuses
          if (latestEvent.payload.steps) {
            const statuses: Record<string, StepStatus> = {};
            latestEvent.payload.steps.forEach((step) => {
              statuses[step.id] = 'pending';
            });
            next.stepStatuses = statuses;
          }
          break;
        }

        case 'plan.awaiting_confirmation': {
          next.status = 'awaiting_confirmation';
          next.plan = latestEvent.payload.plan;
          next.riskLevel = latestEvent.payload.risk_level;
          setIsLoading(false);
          break;
        }

        case 'step.started': {
          next.status = 'executing';
          next.stepStatuses = {
            ...next.stepStatuses,
            [latestEvent.payload.step_id]: 'running',
          };
          break;
        }

        case 'step.completed': {
          next.stepStatuses = {
            ...next.stepStatuses,
            [latestEvent.payload.step_id]: 'completed',
          };
          next.stepResults = {
            ...next.stepResults,
            [latestEvent.payload.step_id]: {
              step_id: latestEvent.payload.step_id,
              tool_name: latestEvent.payload.tool_name,
              server_name: latestEvent.payload.server,
              status: 'completed',
              output: { preview: latestEvent.payload.output_preview },
              error: null,
              attempt_count: 1,
              started_at: latestEvent.payload.started_at,
              completed_at: latestEvent.payload.completed_at,
              duration_ms: latestEvent.payload.duration_ms,
            },
          };
          break;
        }

        case 'step.failed': {
          next.stepStatuses = {
            ...next.stepStatuses,
            [latestEvent.payload.step_id]: 'failed',
          };
          next.stepResults = {
            ...next.stepResults,
            [latestEvent.payload.step_id]: {
              step_id: latestEvent.payload.step_id,
              tool_name: latestEvent.payload.tool_name,
              server_name: latestEvent.payload.server,
              status: 'failed',
              output: null,
              error: {
                classification: latestEvent.payload.error_classification,
                message: latestEvent.payload.error_message,
                retryable: latestEvent.payload.retryable,
                attempt_count: latestEvent.payload.attempt_count,
              },
              attempt_count: latestEvent.payload.attempt_count,
              started_at: latestEvent.payload.started_at,
              completed_at: latestEvent.payload.completed_at,
              duration_ms: null,
            },
          };
          break;
        }

        case 'step.skipped': {
          next.stepStatuses = {
            ...next.stepStatuses,
            [latestEvent.payload.step_id]: 'skipped',
          };
          break;
        }

        case 'escalation.required': {
          next.status = 'paused';
          next.escalation = {
            stepId: latestEvent.payload.step_id,
            reason: latestEvent.payload.reason,
            options: latestEvent.payload.options,
            timeoutSeconds: latestEvent.payload.timeout_seconds,
            impact: latestEvent.payload.impact,
          };
          setIsLoading(false);
          break;
        }

        case 'execution.completed': {
          next.status = 'completed';
          next.summary = latestEvent.payload.summary;
          next.resultPreview = latestEvent.payload.result_preview;
          next.totalDurationMs = latestEvent.payload.total_duration_ms;
          setIsLoading(false);
          // Disconnect SSE after a short delay
          setTimeout(() => disconnect(), 2000);
          break;
        }

        case 'execution.failed': {
          next.status = 'failed';
          next.error = latestEvent.payload.failure_reason;
          next.totalDurationMs = latestEvent.payload.total_duration_ms;
          setIsLoading(false);
          setTimeout(() => disconnect(), 2000);
          break;
        }

        case 'execution.cancelled': {
          next.status = 'cancelled';
          next.error = latestEvent.payload.reason;
          setIsLoading(false);
          setTimeout(() => disconnect(), 2000);
          break;
        }

        case 'heartbeat': {
          // Keepalive - no state change needed
          break;
        }

        case 'error': {
          next.error = latestEvent.payload.message;
          setIsLoading(false);
          break;
        }

        default: {
          // Exhaustiveness check - TypeScript ensures we handle all cases
          const _exhaustive: never = latestEvent;
          console.warn('Unhandled SSE event type:', _exhaustive);
        }
      }

      return next;
    });
  }, [events, disconnect]);

  const submit = useCallback(
    async (
      text: string,
      options: { autoApprove?: boolean; modeOverride?: 'mock' | 'live' | 'mixed' } = {}
    ) => {
      setIsLoading(true);
      setState({
        ...initialState,
        commandText: text,
      });

      try {
        const response = await submitCommand(text, {
          autoApprove: options.autoApprove,
          modeOverride: options.modeOverride,
        });

        setCommandResponse(response);
        currentExecutionIdRef.current = response.execution_id;

        setState((prev) => ({
          ...prev,
          executionId: response.execution_id,
          status: response.status,
          commandText: text,
        }));

        // Connect to SSE stream
        const url = getStreamUrl(response.execution_id);
        setStreamUrl(url);

        // If auto-approved single-step, remain loading
        if (!options.autoApprove && response.status !== 'executing') {
          // Will be set to false when plan.awaiting_confirmation arrives
        }
      } catch (err) {
        setIsLoading(false);
        setState((prev) => ({
          ...prev,
          error: err instanceof Error ? err.message : 'Failed to submit command',
        }));
      }
    },
    []
  );

  const approve = useCallback(async () => {
    if (!state.executionId) return;
    setIsLoading(true);
    try {
      await approveExecution(state.executionId);
      setState((prev) => ({ ...prev, status: 'executing' }));
    } catch (err) {
      setIsLoading(false);
      setState((prev) => ({
        ...prev,
        error: err instanceof Error ? err.message : 'Failed to approve plan',
      }));
    }
  }, [state.executionId]);

  const reject = useCallback(
    async (reason?: string) => {
      if (!state.executionId) return;
      setIsLoading(true);
      try {
        await rejectExecution(state.executionId, reason);
        setState((prev) => ({ ...prev, status: 'cancelled' }));
        setIsLoading(false);
      } catch (err) {
        setIsLoading(false);
        setState((prev) => ({
          ...prev,
          error: err instanceof Error ? err.message : 'Failed to reject plan',
        }));
      }
    },
    [state.executionId]
  );

  const reset = useCallback(() => {
    disconnect();
    setStreamUrl(null);
    setCommandResponse(null);
    setIsLoading(false);
    setState(initialState);
    currentExecutionIdRef.current = null;
  }, [disconnect]);

  return {
    state,
    isLoading,
    isConnected,
    error: state.error || sseError,
    submit,
    approve,
    reject,
    reset,
    events,
  };
}

export default useExecution;
