import React, { useState, useCallback, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ChatThread } from '@/components/ChatThread';
import { ChatInput } from '@/components/ChatInput';
import { PlanDAG } from '@/components/PlanDAG';
import { useExecution } from '@/hooks/useExecution';
import { getExamples } from '@/api/commands';
import { useAuth } from '@/context/AuthContext';
import { useToast } from '@/components/Toast';
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  Wand2,
  KeyRound,
  ShieldCheck,
  ShieldX,
  ChevronRight,
} from 'lucide-react';
import type { ExecutionMode, DemoCommand } from '@/types/api';
import type { ThreadMessage } from '@/components/ChatThread';

export function ChatPage(): JSX.Element {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const executionId = searchParams.get('id');

  const { isAuthenticated, setApiKey } = useAuth();
  const { showSuccess, showError } = useToast();
  const execution = useExecution();

  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [exampleCommands, setExampleCommands] = useState<DemoCommand[]>([]);
  const [showApproval, setShowApproval] = useState(false);

  // Load example commands on mount
  useEffect(() => {
    getExamples()
      .then((data) => setExampleCommands(data.examples))
      .catch(() => {
        // Use fallback examples if API is unavailable
        setExampleCommands([
          {
            title: 'Check Pod Health',
            description: 'Describe pods and check their status in a namespace',
            command: 'Check pod health in the production namespace and restart any that are not running',
            expected_plan_template: 'health-check-and-remediate',
            category: 'health',
          },
          {
            title: 'List ECS Services',
            description: 'List all ECS services in a region',
            command: 'List all ECS services in us-east-1 and show their running count',
            expected_plan_template: 'analysis',
            category: 'analysis',
          },
          {
            title: 'Search GitHub Issues',
            description: 'Search for issues in a GitHub repository',
            command: 'Search for open issues labeled "bug" in the kubernetes/kubernetes repo',
            expected_plan_template: 'analysis',
            category: 'analysis',
          },
        ]);
      });
  }, []);

  // Show approval dialog when plan is awaiting confirmation
  useEffect(() => {
    if (execution.state.status === 'awaiting_confirmation' && execution.state.plan) {
      setShowApproval(true);
    }
  }, [execution.state.status, execution.state.plan]);

  // Handle command submission
  const handleSubmit = useCallback(
    async (text: string, options: { autoApprove: boolean; modeOverride: ExecutionMode | null }) => {
      if (!isAuthenticated) {
        showError('Authentication Required', 'Please enter your API key first.');
        return;
      }

      // Add user message
      const userMsgId = `user-${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        { id: userMsgId, role: 'user', content: text },
      ]);

      // Submit command
      await execution.submit(text, {
        autoApprove: options.autoApprove,
        modeOverride: options.modeOverride ?? undefined,
      });
    },
    [isAuthenticated, showError, execution]
  );

  // Handle system messages based on execution state
  useEffect(() => {
    if (!execution.state.executionId) return;

    const { state } = execution;
    let systemContent = '';
    let metadata: ThreadMessage['metadata'] = undefined;

    if (state.status === 'planning') {
      systemContent = 'Analyzing your command and generating an execution plan...';
    } else if (state.status === 'awaiting_confirmation' && state.plan) {
      const stepCount = state.plan.steps.length;
      const criticalSteps = state.plan.steps.filter((s) => s.critical).length;
      systemContent = `I've generated a plan with **${stepCount} steps**${criticalSteps > 0 ? ` (${criticalSteps} critical)` : ''}.\n\nEstimated duration: **${(state.plan.estimated_duration_ms / 1000).toFixed(1)}s**\n\nPlease review the DAG visualization and click **Approve** to execute, or **Reject** to cancel.`;
      metadata = { planSteps: stepCount, mode: state.executionId ? undefined : undefined };
    } else if (state.status === 'executing') {
      const completed = Object.values(state.stepStatuses).filter((s) => s === 'completed').length;
      const total = Object.keys(state.stepStatuses).length;
      systemContent = `Executing plan... (${completed}/${total} steps completed)`;
    } else if (state.status === 'completed') {
      systemContent = state.summary
        ? `## Execution Complete\n\n${state.summary}`
        : '## Execution Complete\n\nAll steps executed successfully.';
      if (state.resultPreview) {
        systemContent += `\n\n\`\`\`json\n${JSON.stringify(state.resultPreview, null, 2)}\n\`\`\``;
      }
      metadata = {
        executionTime: state.totalDurationMs ?? undefined,
        mode: execution.state.executionId ? undefined : undefined,
      };
    } else if (state.status === 'failed') {
      systemContent = `## Execution Failed\n\n${state.error || 'An unknown error occurred.'}`;
    } else if (state.status === 'cancelled') {
      systemContent = 'Execution was cancelled.';
    }

    if (systemContent) {
      const sysMsgId = `sys-${execution.state.executionId}-${state.status}`;
      setMessages((prev) => {
        // Check if we already have this message
        const existing = prev.find((m) => m.id === sysMsgId);
        if (existing) {
          return prev.map((m) => (m.id === sysMsgId ? { ...m, content: systemContent, metadata } : m));
        }
        return [...prev, { id: sysMsgId, role: 'system', content: systemContent, metadata }];
      });
    }
  }, [
    execution.state.status,
    execution.state.plan,
    execution.state.summary,
    execution.state.error,
    execution.state.resultPreview,
    execution.state.totalDurationMs,
    execution.state.stepStatuses,
    execution.state.executionId,
  ]);

  // Handle API key submission
  const handleSetApiKey = useCallback(() => {
    if (apiKeyInput.trim()) {
      setApiKey(apiKeyInput.trim());
      setApiKeyInput('');
      showSuccess('API Key Set', 'You are now authenticated.');
    }
  }, [apiKeyInput, setApiKey, showSuccess]);

  // Determine loading text
  const getLoadingText = (): string => {
    if (execution.state.status === 'planning') return 'Generating plan...';
    if (execution.state.status === 'executing') return 'Executing steps...';
    if (execution.isLoading) return 'Processing...';
    return '';
  };

  const isLoading = execution.isLoading || execution.state.status === 'executing';

  return (
    <div className="h-full flex flex-col">
      {/* API Key Input Banner (when not authenticated) */}
      {!isAuthenticated && (
        <div className="shrink-0 bg-amber-50 border-b border-amber-200 px-4 py-3">
          <div className="flex items-center gap-3 max-w-xl">
            <KeyRound size={16} className="text-amber-500 shrink-0" />
            <div className="flex-1">
              <p className="text-xs font-medium text-amber-800">
                Enter your API key to start using OpsMate
              </p>
              <p className="text-2xs text-amber-600 mt-0.5">
                In MOCK mode, you can use any non-empty key.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="password"
                value={apiKeyInput}
                onChange={(e) => setApiKeyInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSetApiKey()}
                placeholder="API Key"
                className="text-xs bg-white border border-amber-200 rounded-lg px-3 py-1.5 w-48 focus:outline-none focus:ring-1 focus:ring-amber-400"
              />
              <button
                onClick={handleSetApiKey}
                className="text-xs bg-amber-600 text-white px-3 py-1.5 rounded-lg hover:bg-amber-700 transition-colors font-medium"
              >
                Set Key
              </button>
            </div>
          </div>
        </div>
      )}

      {/* LIVE Mode Warning */}
      {/* Note: Mode indicator is in the header, but we show an additional banner for LIVE */}

      {/* Main Content Area */}
      <div className="flex-1 flex min-h-0">
        {/* Chat Area */}
        <div className="flex-1 flex flex-col min-w-0">
          <ChatThread
            messages={messages}
            isLoading={isLoading}
            loadingText={getLoadingText()}
          />

          {/* Plan Approval Bar */}
          {showApproval && execution.state.plan && (
            <div className="shrink-0 bg-opsmate-50 border-t border-opsmate-200 px-4 py-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <ShieldCheck size={16} className="text-opsmate-600" />
                  <div>
                    <p className="text-sm font-medium text-opsmate-800">
                      Plan Ready for Approval
                    </p>
                    <p className="text-2xs text-opsmate-500">
                      {execution.state.plan.steps.length} steps
                      {execution.state.riskLevel && (
                        <span className={`ml-2 font-semibold ${
                          execution.state.riskLevel === 'HIGH'
                            ? 'text-red-600'
                            : execution.state.riskLevel === 'MEDIUM'
                            ? 'text-amber-600'
                            : 'text-green-600'
                        }`}>
                          Risk: {execution.state.riskLevel}
                        </span>
                      )}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => {
                      execution.reject();
                      setShowApproval(false);
                    }}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 border border-red-200 transition-colors"
                  >
                    <ShieldX size={14} />
                    Reject
                  </button>
                  <button
                    onClick={() => {
                      execution.approve();
                      setShowApproval(false);
                    }}
                    className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium text-white bg-opsmate-800 hover:bg-opsmate-700 transition-colors shadow-soft"
                  >
                    <ShieldCheck size={14} />
                    Approve
                    <ChevronRight size={12} />
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Chat Input */}
          <ChatInput
            onSubmit={handleSubmit}
            isLoading={isLoading}
            disabled={!isAuthenticated}
            exampleCommands={exampleCommands}
          />
        </div>

        {/* DAG Panel (shown when there's a plan) */}
        {execution.state.plan && (
          <div className="w-[45%] min-w-[400px] border-l border-opsmate-200 bg-white flex flex-col shrink-0">
            <PlanDAG
              plan={execution.state.plan}
              stepStatuses={execution.state.stepStatuses}
              stepResults={execution.state.stepResults}
              isExecuting={execution.state.status === 'executing'}
              className="h-full"
            />
          </div>
        )}
      </div>
    </div>
  );
}

export default ChatPage;
