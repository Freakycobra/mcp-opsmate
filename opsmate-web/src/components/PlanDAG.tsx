import React, { useMemo, useCallback, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeProps,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  Panel,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Play,
  CheckCircle2,
  XCircle,
  Loader2,
  SkipForward,
  Clock,
  Server,
  Wrench,
  AlertTriangle,
  Maximize2,
  X,
} from 'lucide-react';
import type { ExecutionPlan, StepStatus, StepResult } from '@/types/api';

// ─── Types ─────────────────────────────────────────────────────────

export interface PlanDAGProps {
  /** The execution plan to visualize */
  plan: ExecutionPlan;
  /** Current status of each step */
  stepStatuses: Record<string, StepStatus>;
  /** Results for completed/failed steps */
  stepResults: Record<string, StepResult>;
  /** Whether the DAG is currently being executed */
  isExecuting?: boolean;
  /** Callback when a node is clicked */
  onNodeClick?: (stepId: string) => void;
  /** Additional className */
  className?: string;
}

interface StepNodeData {
  stepId: string;
  toolName: string;
  server: string;
  status: StepStatus;
  isCritical: boolean;
  result?: StepResult;
  index: number;
}

// ─── Step Status Config ────────────────────────────────────────────

const STATUS_CONFIG: Record<StepStatus, {
  icon: React.ReactNode;
  nodeClass: string;
  handleClass: string;
  label: string;
}> = {
  pending: {
    icon: <Clock size={14} />,
    nodeClass: 'step-node-pending',
    handleClass: '!bg-opsmate-400',
    label: 'Pending',
  },
  running: {
    icon: <Loader2 size={14} className="animate-spin" />,
    nodeClass: 'step-node-running',
    handleClass: '!bg-blue-500',
    label: 'Running',
  },
  completed: {
    icon: <CheckCircle2 size={14} />,
    nodeClass: 'step-node-completed',
    handleClass: '!bg-green-500',
    label: 'Completed',
  },
  failed: {
    icon: <XCircle size={14} />,
    nodeClass: 'step-node-failed',
    handleClass: '!bg-red-500',
    label: 'Failed',
  },
  skipped: {
    icon: <SkipForward size={14} />,
    nodeClass: 'step-node-skipped',
    handleClass: '!bg-gray-300',
    label: 'Skipped',
  },
  skipped_due_to_dependency: {
    icon: <SkipForward size={14} />,
    nodeClass: 'step-node-skipped',
    handleClass: '!bg-gray-300',
    label: 'Skipped',
  },
  retrying: {
    icon: <Loader2 size={14} className="animate-spin" />,
    nodeClass: 'step-node-running',
    handleClass: '!bg-amber-500',
    label: 'Retrying',
  },
};

// ─── Custom Step Node ──────────────────────────────────────────────

function StepNode({ data, selected }: NodeProps<StepNodeData>): JSX.Element {
  const config = STATUS_CONFIG[data.status];
  const [showTooltip, setShowTooltip] = useState(false);

  const duration = data.result?.duration_ms
    ? `${(data.result.duration_ms / 1000).toFixed(1)}s`
    : null;

  return (
    <div
      className={`step-node ${config.nodeClass} ${selected ? 'ring-2 ring-offset-1 ring-opsmate-400' : ''} ${
        data.isCritical ? '!border-red-300 shadow-md' : ''
      }`}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <Handle type="target" position={Position.Top} className={config.handleClass} />

      <div className="flex items-center gap-2 mb-1">
        <span className="text-opsmate-400">{config.icon}</span>
        <span className="font-semibold text-xs truncate flex-1" title={data.toolName}>
          {data.toolName}
        </span>
        {data.isCritical && (
          <AlertTriangle size={10} className="text-red-400 shrink-0" title="Critical step" />
        )}
      </div>

      <div className="flex items-center gap-1 text-2xs text-opsmate-400">
        <Server size={10} />
        <span className="truncate">{data.server}</span>
      </div>

      <div className="flex items-center justify-between mt-1.5">
        <span className={`text-2xs font-medium px-1.5 py-0.5 rounded ${
          data.status === 'completed' ? 'bg-green-100 text-green-700' :
          data.status === 'failed' ? 'bg-red-100 text-red-700' :
          data.status === 'running' ? 'bg-blue-100 text-blue-700' :
          'bg-opsmate-100 text-opsmate-500'
        }`}>
          #{data.index + 1} {config.label}
        </span>
        {duration && (
          <span className="text-2xs text-opsmate-400 font-mono">{duration}</span>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} className={config.handleClass} />

      {/* Tooltip on hover */}
      {showTooltip && data.result?.output && (
        <div className="absolute left-full ml-2 top-0 z-50 w-64 p-3 bg-white rounded-lg shadow-elevated border border-opsmate-200 text-xs animate-enter">
          <p className="font-semibold text-opsmate-700 mb-1">Output Preview</p>
          <pre className="text-2xs text-opsmate-500 overflow-hidden whitespace-pre-wrap max-h-32 overflow-y-auto">
            {JSON.stringify(data.result.output, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

const nodeTypes = {
  step: StepNode,
};

// ─── Layout Engine ─────────────────────────────────────────────────

/**
 * Auto-position nodes in a top-down DAG layout.
 * Uses a simple level-based algorithm:
 * - Compute topological levels (depth from root nodes)
 * - Position nodes at their level vertically
 * - Spread nodes horizontally within each level
 */
function autoLayout(
  plan: ExecutionPlan,
  statuses: Record<string, StepStatus>,
  results: Record<string, StepResult>
): { nodes: Node<StepNodeData>[]; edges: Edge[] } {
  const { steps, dependencies } = plan;

  // Compute in-degree for each step
  const inDegree: Record<string, number> = {};
  steps.forEach((step) => {
    inDegree[step.id] = 0;
  });
  steps.forEach((step) => {
    const deps = dependencies[step.id] || [];
    deps.forEach((depId) => {
      // depId is a prerequisite for step.id
      // So step.id depends on depId
      inDegree[step.id] = (inDegree[step.id] || 0) + 1;
    });
  });

  // Compute levels using BFS (topological)
  const levels: Record<string, number> = {};
  const queue: string[] = [];

  steps.forEach((step) => {
    if (inDegree[step.id] === 0) {
      levels[step.id] = 0;
      queue.push(step.id);
    }
  });

  // Build reverse dependency map (who depends on me)
  const dependents: Record<string, string[]> = {};
  steps.forEach((step) => {
    dependents[step.id] = [];
  });
  steps.forEach((step) => {
    const deps = dependencies[step.id] || [];
    deps.forEach((depId) => {
      if (dependents[depId]) {
        dependents[depId].push(step.id);
      }
    });
  });

  // BFS to compute levels
  const processed = new Set<string>();
  while (queue.length > 0) {
    const current = queue.shift()!;
    processed.add(current);

    const currentLevel = levels[current] || 0;
    const deps = dependents[current] || [];

    deps.forEach((depId) => {
      levels[depId] = Math.max(levels[depId] || 0, currentLevel + 1);
      // Check if all prerequisites are processed
      const prereqs = dependencies[depId] || [];
      const allPrereqsDone = prereqs.every((p) => processed.has(p));
      if (allPrereqsDone && !queue.includes(depId)) {
        queue.push(depId);
      }
    });
  }

  // For any unprocessed nodes (shouldn't happen with valid DAG), assign level 0
  steps.forEach((step) => {
    if (levels[step.id] === undefined) {
      levels[step.id] = 0;
    }
  });

  // Group nodes by level
  const levelGroups: Record<number, string[]> = {};
  steps.forEach((step) => {
    const level = levels[step.id] || 0;
    if (!levelGroups[level]) levelGroups[level] = [];
    levelGroups[level].push(step.id);
  });

  // Position nodes
  const NODE_WIDTH = 180;
  const NODE_HEIGHT = 90;
  const HORIZONTAL_GAP = 40;
  const VERTICAL_GAP = 60;

  const nodes: Node<StepNodeData>[] = steps.map((step, index) => {
    const level = levels[step.id] || 0;
    const siblings = levelGroups[level] || [];
    const siblingIndex = siblings.indexOf(step.id);
    const siblingsCount = siblings.length;

    // Center the level
    const levelWidth = siblingsCount * NODE_WIDTH + (siblingsCount - 1) * HORIZONTAL_GAP;
    const startX = -levelWidth / 2;
    const x = startX + siblingIndex * (NODE_WIDTH + HORIZONTAL_GAP);
    const y = level * (NODE_HEIGHT + VERTICAL_GAP);

    return {
      id: step.id,
      type: 'step',
      position: { x, y },
      data: {
        stepId: step.id,
        toolName: step.tool_name,
        server: step.server,
        status: statuses[step.id] || 'pending',
        isCritical: step.critical,
        result: results[step.id],
        index,
      },
    };
  });

  // Create edges from dependencies
  const edges: Edge[] = [];
  steps.forEach((step) => {
    const deps = dependencies[step.id] || [];
    deps.forEach((depId) => {
      const sourceStatus = statuses[depId] || 'pending';
      const isActive = sourceStatus === 'running' || sourceStatus === 'completed';

      edges.push({
        id: `${depId}->${step.id}`,
        source: depId,
        target: step.id,
        animated: isActive,
        style: {
          stroke: sourceStatus === 'failed' ? '#f0a8a0' :
                  sourceStatus === 'completed' ? '#a8d8b8' :
                  sourceStatus === 'running' ? '#a8c4f0' :
                  '#d4c8b8',
          strokeWidth: 2,
        },
        type: 'smoothstep',
      });
    });
  });

  return { nodes, edges };
}

// ─── PlanDAG Component ─────────────────────────────────────────────

export function PlanDAG({
  plan,
  stepStatuses,
  stepResults,
  isExecuting = false,
  onNodeClick,
  className = '',
}: PlanDAGProps): JSX.Element {
  const [selectedStep, setSelectedStep] = useState<string | null>(null);
  const [isExpanded, setIsExpanded] = useState(false);

  // Compute nodes and edges
  const { initialNodes, initialEdges } = useMemo(
    () => autoLayout(plan, stepStatuses, stepResults),
    [plan, stepStatuses, stepResults]
  );

  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  // Update nodes when statuses change
  React.useEffect(() => {
    const { nodes: newNodes, edges: newEdges } = autoLayout(plan, stepStatuses, stepResults);
    // Merge to preserve positions
    onNodesChange(
      newNodes.map((n) => ({
        type: 'replace' as const,
        item: n,
        id: n.id,
      }))
    );
    onEdgesChange(
      newEdges.map((e) => ({
        type: 'replace' as const,
        item: e,
        id: e.id,
      }))
    );
  }, [plan, stepStatuses, stepResults, onNodesChange, onEdgesChange]);

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedStep((prev) => (prev === node.id ? null : node.id));
      onNodeClick?.(node.id);
    },
    [onNodeClick]
  );

  // Compute summary stats
  const totalSteps = plan.steps.length;
  const completedSteps = Object.values(stepStatuses).filter((s) => s === 'completed').length;
  const failedSteps = Object.values(stepStatuses).filter((s) => s === 'failed').length;
  const runningSteps = Object.values(stepStatuses).filter((s) => s === 'running').length;

  const selectedStepData = selectedStep
    ? plan.steps.find((s) => s.id === selectedStep)
    : null;
  const selectedResult = selectedStep ? stepResults[selectedStep] : null;
  const selectedStatus = selectedStep ? stepStatuses[selectedStep] : null;

  const flowContent = (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={handleNodeClick}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.3 }}
      minZoom={0.2}
      maxZoom={2}
      attributionPosition="bottom-left"
      proOptions={{ hideAttribution: true }}
    >
      <Background color="#d4c8b8" gap={20} size={1} />
      <Controls />
      <MiniMap
        nodeColor={(node) => {
          const status = (node.data?.status as StepStatus) || 'pending';
          switch (status) {
            case 'completed': return '#a8d8b8';
            case 'failed': return '#f0a8a0';
            case 'running': return '#a8c4f0';
            case 'skipped': return '#cccccc';
            default: return '#d4c8b8';
          }
        }}
        maskColor="rgba(250, 248, 245, 0.7)"
        className="!bg-white/80 !border-opsmate-200 !rounded-lg"
      />

      {/* Status panel */}
      <Panel position="top-left" className="m-2">
        <div className="bg-white/90 backdrop-blur-sm rounded-lg border border-opsmate-200 shadow-soft px-3 py-2 text-xs">
          <div className="flex items-center gap-3">
            <span className="font-medium text-opsmate-700">
              {totalSteps} steps
            </span>
            {isExecuting && (
              <span className="flex items-center gap-1 text-blue-600">
                <Loader2 size={10} className="animate-spin" />
                Executing...
              </span>
            )}
            <div className="flex items-center gap-2">
              {completedSteps > 0 && (
                <span className="flex items-center gap-1 text-green-600">
                  <CheckCircle2 size={10} />
                  {completedSteps}
                </span>
              )}
              {failedSteps > 0 && (
                <span className="flex items-center gap-1 text-red-600">
                  <XCircle size={10} />
                  {failedSteps}
                </span>
              )}
              {runningSteps > 0 && (
                <span className="flex items-center gap-1 text-blue-600">
                  <Play size={10} />
                  {runningSteps}
                </span>
              )}
            </div>
          </div>
          {/* Progress bar */}
          <div className="mt-1.5 h-1 bg-opsmate-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-green-400 transition-all duration-500 rounded-full"
              style={{ width: `${totalSteps > 0 ? (completedSteps / totalSteps) * 100 : 0}%` }}
            />
          </div>
        </div>
      </Panel>
    </ReactFlow>
  );

  return (
    <div className={`flex flex-col ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-white border-b border-opsmate-200 shrink-0">
        <div className="flex items-center gap-2">
          <Wrench size={14} className="text-opsmate-500" />
          <span className="text-sm font-semibold text-opsmate-800">Execution Plan</span>
          <span className="text-2xs text-opsmate-400">
            Estimated: {(plan.estimated_duration_ms / 1000).toFixed(1)}s
          </span>
        </div>
        <button
          onClick={() => setIsExpanded((prev) => !prev)}
          className="p-1.5 rounded-md hover:bg-opsmate-100 text-opsmate-400 hover:text-opsmate-600 transition-colors"
          title={isExpanded ? 'Collapse' : 'Expand'}
        >
          {isExpanded ? <X size={14} /> : <Maximize2 size={14} />}
        </button>
      </div>

      {/* DAG + Detail Panel */}
      <div className="flex-1 flex min-h-0">
        <div className={`flex-1 min-w-0 ${isExpanded ? 'h-[70vh]' : 'h-64'}`}>
          {flowContent}
        </div>

        {/* Step detail sidebar */}
        {selectedStepData && (
          <div className="w-72 border-l border-opsmate-200 bg-white overflow-y-auto shrink-0 animate-enter">
            <div className="p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-opsmate-800">
                  Step {plan.steps.indexOf(selectedStepData) + 1}
                </h3>
                <button
                  onClick={() => setSelectedStep(null)}
                  className="p-0.5 rounded hover:bg-opsmate-100 text-opsmate-400"
                >
                  <X size={14} />
                </button>
              </div>

              <div className="space-y-3">
                <div>
                  <label className="text-2xs font-medium text-opsmate-400 uppercase tracking-wider">
                    Tool
                  </label>
                  <p className="text-sm font-mono text-opsmate-800 mt-0.5">
                    {selectedStepData.tool_name}
                  </p>
                </div>

                <div>
                  <label className="text-2xs font-medium text-opsmate-400 uppercase tracking-wider">
                    Server
                  </label>
                  <p className="text-sm text-opsmate-700 mt-0.5">{selectedStepData.server}</p>
                </div>

                <div>
                  <label className="text-2xs font-medium text-opsmate-400 uppercase tracking-wider">
                    Status
                  </label>
                  <div className="mt-0.5">
                    {selectedStatus && (
                      <span className={`status-badge ${
                        selectedStatus === 'completed' ? 'bg-green-50 text-green-700 border-green-200' :
                        selectedStatus === 'failed' ? 'bg-red-50 text-red-700 border-red-200' :
                        selectedStatus === 'running' ? 'bg-blue-50 text-blue-700 border-blue-200' :
                        'bg-opsmate-50 text-opsmate-600 border-opsmate-200'
                      }`}>
                        {STATUS_CONFIG[selectedStatus].icon}
                        {STATUS_CONFIG[selectedStatus].label}
                      </span>
                    )}
                  </div>
                </div>

                {selectedStepData.critical && (
                  <div className="flex items-center gap-1.5 text-2xs text-red-600 bg-red-50 p-2 rounded">
                    <AlertTriangle size={12} />
                    <span className="font-medium">Critical step - destructive operation</span>
                  </div>
                )}

                {selectedResult?.duration_ms && (
                  <div>
                    <label className="text-2xs font-medium text-opsmate-400 uppercase tracking-wider">
                      Duration
                    </label>
                    <p className="text-sm font-mono text-opsmate-700 mt-0.5">
                      {(selectedResult.duration_ms / 1000).toFixed(2)}s
                    </p>
                  </div>
                )}

                {selectedResult?.output && (
                  <div>
                    <label className="text-2xs font-medium text-opsmate-400 uppercase tracking-wider">
                      Output
                    </label>
                    <pre className="mt-1 p-2 bg-opsmate-50 rounded text-2xs font-mono text-opsmate-700 overflow-x-auto max-h-48 overflow-y-auto">
                      {JSON.stringify(selectedResult.output, null, 2)}
                    </pre>
                  </div>
                )}

                {selectedResult?.error && (
                  <div>
                    <label className="text-2xs font-medium text-opsmate-400 uppercase tracking-wider">
                      Error
                    </label>
                    <div className="mt-1 p-2 bg-red-50 rounded border border-red-100">
                      <p className="text-2xs font-medium text-red-700">
                        {selectedResult.error.classification}
                      </p>
                      <p className="text-2xs text-red-600 mt-1">
                        {selectedResult.error.message}
                      </p>
                    </div>
                  </div>
                )}

                {selectedStepData.condition && (
                  <div>
                    <label className="text-2xs font-medium text-opsmate-400 uppercase tracking-wider">
                      Condition
                    </label>
                    <p className="text-2xs font-mono text-opsmate-600 mt-0.5 bg-opsmate-50 p-2 rounded">
                      {selectedStepData.condition}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default PlanDAG;
