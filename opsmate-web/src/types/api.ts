import { z } from 'zod';

// ─── Execution Status ──────────────────────────────────────────────

export const ExecutionStatusSchema = z.enum([
  'pending',
  'planning',
  'awaiting_confirmation',
  'executing',
  'paused',
  'completed',
  'failed',
  'cancelled',
]);
export type ExecutionStatus = z.infer<typeof ExecutionStatusSchema>;

export const StepStatusSchema = z.enum([
  'pending',
  'running',
  'completed',
  'failed',
  'skipped',
  'skipped_due_to_dependency',
  'retrying',
]);
export type StepStatus = z.infer<typeof StepStatusSchema>;

export const ExecutionModeSchema = z.enum(['mock', 'live', 'mixed']);
export type ExecutionMode = z.infer<typeof ExecutionModeSchema>;

export const ErrorTypeSchema = z.enum([
  'transient',
  'permanent',
  'configuration',
  'unknown',
]);
export type ErrorType = z.infer<typeof ErrorTypeSchema>;

// ─── Command ───────────────────────────────────────────────────────

export const CommandRequestSchema = z.object({
  text: z.string().min(1).max(2000),
  auto_approve: z.boolean().default(false),
  metadata: z.record(z.unknown()).default({}),
  execution_mode_override: ExecutionModeSchema.nullable().default(null),
});
export type CommandRequest = z.infer<typeof CommandRequestSchema>;

export const CommandResponseSchema = z.object({
  execution_id: z.string().uuid(),
  status: ExecutionStatusSchema,
  message: z.string(),
  execution_mode: ExecutionModeSchema,
  stream_url: z.string(),
});
export type CommandResponse = z.infer<typeof CommandResponseSchema>;

// ─── Execution Plan ────────────────────────────────────────────────

export const PlanStepSchema = z.object({
  id: z.string(),
  tool_name: z.string(),
  server: z.string(),
  input_schema: z.record(z.unknown()),
  output_schema: z.record(z.unknown()).nullable(),
  critical: z.boolean().default(false),
  condition: z.string().nullable().default(null),
});
export type PlanStep = z.infer<typeof PlanStepSchema>;

export const ExecutionPlanSchema = z.object({
  steps: z.array(PlanStepSchema),
  dependencies: z.record(z.array(z.string())),
  estimated_duration_ms: z.number().int(),
});
export type ExecutionPlan = z.infer<typeof ExecutionPlanSchema>;

// ─── Step Result ───────────────────────────────────────────────────

export const StepErrorSchema = z.object({
  classification: ErrorTypeSchema,
  message: z.string(),
  retryable: z.boolean(),
  attempt_count: z.number().int(),
});
export type StepError = z.infer<typeof StepErrorSchema>;

export const StepResultSchema = z.object({
  step_id: z.string(),
  tool_name: z.string(),
  server_name: z.string(),
  status: StepStatusSchema,
  output: z.record(z.unknown()).nullable(),
  error: StepErrorSchema.nullable(),
  attempt_count: z.number().int().default(1),
  started_at: z.string().datetime().nullable(),
  completed_at: z.string().datetime().nullable(),
  duration_ms: z.number().nullable(),
});
export type StepResult = z.infer<typeof StepResultSchema>;

// ─── Execution State ───────────────────────────────────────────────

export const ExecutionContextSchema = z.object({
  variables: z.record(z.unknown()).default({}),
  metadata: z.record(z.unknown()).default({}),
  secrets_redacted: z.boolean().default(true),
});
export type ExecutionContext = z.infer<typeof ExecutionContextSchema>;

export const AuditLogEntrySchema = z.object({
  id: z.string().uuid(),
  action: z.string(),
  details: z.record(z.unknown()),
  timestamp: z.string().datetime(),
  user_id: z.string().nullable(),
});
export type AuditLogEntry = z.infer<typeof AuditLogEntrySchema>;

export const ExecutionDetailSchema = z.object({
  execution_id: z.string().uuid(),
  status: ExecutionStatusSchema,
  command_text: z.string(),
  execution_mode: z.string(),
  plan: ExecutionPlanSchema.nullable(),
  results: z.record(StepResultSchema),
  context: ExecutionContextSchema,
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
  completed_at: z.string().datetime().nullable(),
  planning_duration_ms: z.number().nullable(),
  total_duration_ms: z.number().nullable(),
  audit_log: z.array(AuditLogEntrySchema),
});
export type ExecutionDetail = z.infer<typeof ExecutionDetailSchema>;

// ─── Execution Summary (for list) ──────────────────────────────────

export const ExecutionSummarySchema = z.object({
  execution_id: z.string().uuid(),
  status: ExecutionStatusSchema,
  command_text: z.string(),
  execution_mode: z.string(),
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
  completed_at: z.string().datetime().nullable(),
  total_duration_ms: z.number().nullable(),
  step_count: z.number().int(),
  failed_steps: z.number().int(),
});
export type ExecutionSummary = z.infer<typeof ExecutionSummarySchema>;

export const ExecutionListResponseSchema = z.object({
  items: z.array(ExecutionSummarySchema),
  total: z.number().int(),
  page: z.number().int(),
  page_size: z.number().int(),
  total_pages: z.number().int(),
});
export type ExecutionListResponse = z.infer<typeof ExecutionListResponseSchema>;

// ─── SSE Event Types ───────────────────────────────────────────────

export const SSEEventTypeSchema = z.enum([
  'execution.created',
  'plan.generated',
  'plan.awaiting_confirmation',
  'step.started',
  'step.completed',
  'step.failed',
  'step.skipped',
  'escalation.required',
  'execution.completed',
  'execution.failed',
  'execution.cancelled',
  'heartbeat',
  'error',
]);
export type SSEEventType = z.infer<typeof SSEEventTypeSchema>;

// ─── SSE Event Payload Schemas ─────────────────────────────────────

export const StepStartedPayloadSchema = z.object({
  step_id: z.string(),
  tool_name: z.string(),
  server: z.string(),
  started_at: z.string().datetime(),
});
export type StepStartedPayload = z.infer<typeof StepStartedPayloadSchema>;

export const StepCompletedPayloadSchema = z.object({
  step_id: z.string(),
  tool_name: z.string(),
  server: z.string(),
  status: z.literal('completed'),
  output_preview: z.string(),
  started_at: z.string().datetime(),
  completed_at: z.string().datetime(),
  duration_ms: z.number(),
});
export type StepCompletedPayload = z.infer<typeof StepCompletedPayloadSchema>;

export const StepFailedPayloadSchema = z.object({
  step_id: z.string(),
  tool_name: z.string(),
  server: z.string(),
  status: z.literal('failed'),
  error_classification: ErrorTypeSchema,
  error_message: z.string(),
  retryable: z.boolean(),
  attempt_count: z.number().int(),
  started_at: z.string().datetime(),
  completed_at: z.string().datetime().nullable(),
});
export type StepFailedPayload = z.infer<typeof StepFailedPayloadSchema>;

export const EscalationEventSchema = z.object({
  step_id: z.string(),
  reason: z.string(),
  options: z.array(z.string()),
  timeout_seconds: z.number().int().default(300),
  impact: z.string(),
});
export type EscalationEvent = z.infer<typeof EscalationEventSchema>;

export const ExecutionCompletedPayloadSchema = z.object({
  execution_id: z.string().uuid(),
  status: z.literal('completed'),
  summary: z.string(),
  result_preview: z.record(z.unknown()),
  total_duration_ms: z.number(),
  completed_at: z.string().datetime(),
});
export type ExecutionCompletedPayload = z.infer<typeof ExecutionCompletedPayloadSchema>;

export const ExecutionFailedPayloadSchema = z.object({
  execution_id: z.string().uuid(),
  status: z.literal('failed'),
  failure_reason: z.string(),
  failed_step_id: z.string().nullable(),
  total_duration_ms: z.number(),
  completed_at: z.string().datetime(),
});
export type ExecutionFailedPayload = z.infer<typeof ExecutionFailedPayloadSchema>;

export const ExecutionCancelledPayloadSchema = z.object({
  execution_id: z.string().uuid(),
  status: z.literal('cancelled'),
  reason: z.string(),
  cancelled_at: z.string().datetime(),
});
export type ExecutionCancelledPayload = z.infer<typeof ExecutionCancelledPayloadSchema>;

// ─── Discriminated SSE Event Union ─────────────────────────────────

export const SSEEventSchema = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('execution.created'),
    payload: z.object({ execution_id: z.string().uuid(), status: ExecutionStatusSchema, message: z.string() }),
  }),
  z.object({
    type: z.literal('plan.generated'),
    payload: ExecutionPlanSchema,
  }),
  z.object({
    type: z.literal('plan.awaiting_confirmation'),
    payload: z.object({
      execution_id: z.string().uuid(),
      plan: ExecutionPlanSchema,
      risk_level: z.enum(['LOW', 'MEDIUM', 'HIGH']),
    }),
  }),
  z.object({
    type: z.literal('step.started'),
    payload: StepStartedPayloadSchema,
  }),
  z.object({
    type: z.literal('step.completed'),
    payload: StepCompletedPayloadSchema,
  }),
  z.object({
    type: z.literal('step.failed'),
    payload: StepFailedPayloadSchema,
  }),
  z.object({
    type: z.literal('step.skipped'),
    payload: z.object({ step_id: z.string(), reason: z.string() }),
  }),
  z.object({
    type: z.literal('escalation.required'),
    payload: EscalationEventSchema,
  }),
  z.object({
    type: z.literal('execution.completed'),
    payload: ExecutionCompletedPayloadSchema,
  }),
  z.object({
    type: z.literal('execution.failed'),
    payload: ExecutionFailedPayloadSchema,
  }),
  z.object({
    type: z.literal('execution.cancelled'),
    payload: ExecutionCancelledPayloadSchema,
  }),
  z.object({
    type: z.literal('heartbeat'),
    payload: z.object({ timestamp: z.string().datetime() }),
  }),
  z.object({
    type: z.literal('error'),
    payload: z.object({ message: z.string(), code: z.string() }),
  }),
]);
export type SSEEvent = z.infer<typeof SSEEventSchema>;

// ─── Health ────────────────────────────────────────────────────────

export const HealthCheckDetailSchema = z.object({
  status: z.enum(['ok', 'warning', 'critical']),
  response_time_ms: z.number(),
  detail: z.string().nullable(),
});
export type HealthCheckDetail = z.infer<typeof HealthCheckDetailSchema>;

export const HealthResponseSchema = z.object({
  status: z.enum(['healthy', 'degraded', 'unhealthy']),
  version: z.string(),
  uptime_seconds: z.number(),
  timestamp: z.string().datetime(),
  checks: z.record(HealthCheckDetailSchema),
});
export type HealthResponse = z.infer<typeof HealthResponseSchema>;

// ─── Examples ──────────────────────────────────────────────────────

export const DemoCommandSchema = z.object({
  title: z.string(),
  description: z.string(),
  command: z.string(),
  expected_plan_template: z.string(),
  category: z.string(),
});
export type DemoCommand = z.infer<typeof DemoCommandSchema>;

export const ExamplesResponseSchema = z.object({
  examples: z.array(DemoCommandSchema),
});
export type ExamplesResponse = z.infer<typeof ExamplesResponseSchema>;

// ─── Admin ─────────────────────────────────────────────────────────

export const ModeConfigurationResponseSchema = z.object({
  global_mode: ExecutionModeSchema,
  effective_mode: ExecutionModeSchema,
  server_modes: z.record(z.enum(['mock', 'live', 'local'])),
  can_switch_at_runtime: z.boolean(),
  active_executions: z.number().int(),
  last_changed_at: z.string().datetime().nullable(),
  last_changed_by: z.string().nullable(),
});
export type ModeConfigurationResponse = z.infer<typeof ModeConfigurationResponseSchema>;

export const ModeSwitchRequestSchema = z.object({
  global_mode: ExecutionModeSchema,
  server_overrides: z.record(z.enum(['mock', 'live', 'local'])).default({}),
  reason: z.string().min(1),
  force: z.boolean().default(false),
});
export type ModeSwitchRequest = z.infer<typeof ModeSwitchRequestSchema>;

export const ModeSwitchResponseSchema = z.object({
  previous_mode: z.string(),
  new_mode: z.string(),
  applied_at: z.string().datetime(),
  active_executions_unchanged: z.number().int(),
  message: z.string(),
});
export type ModeSwitchResponse = z.infer<typeof ModeSwitchResponseSchema>;

// ─── Tool Registry ─────────────────────────────────────────────────

export const ToolInfoSchema = z.object({
  name: z.string(),
  description: z.string(),
  input_schema: z.record(z.unknown()),
  output_schema: z.record(z.unknown()).nullable(),
  server: z.string(),
  destructive: z.boolean().default(false),
});
export type ToolInfo = z.infer<typeof ToolInfoSchema>;

export const ServerToolsInfoSchema = z.object({
  server_name: z.string(),
  transport: z.string(),
  connected: z.boolean(),
  mode: z.enum(['mock', 'live', 'local']),
  tool_count: z.number().int(),
  tools: z.array(ToolInfoSchema),
});
export type ServerToolsInfo = z.infer<typeof ServerToolsInfoSchema>;

export const ToolRegistryResponseSchema = z.object({
  last_refreshed_at: z.string().datetime(),
  server_count: z.number().int(),
  total_tools: z.number().int(),
  servers: z.array(ServerToolsInfoSchema),
});
export type ToolRegistryResponse = z.infer<typeof ToolRegistryResponseSchema>;

export const ToolRefreshResponseSchema = z.object({
  refreshed_at: z.string().datetime(),
  servers_discovered: z.number().int(),
  tools_discovered: z.number().int(),
  servers: z.array(z.object({
    server_name: z.string(),
    status: z.enum(['ok', 'failed', 'timeout']),
    tools_found: z.number().int(),
    error: z.string().nullable(),
  })),
});
export type ToolRefreshResponse = z.infer<typeof ToolRefreshResponseSchema>;

// ─── Plan Approval ─────────────────────────────────────────────────

export const PlanApprovalRequestSchema = z.object({
  decision: z.enum(['approve', 'reject', 'modify']),
  modified_plan: ExecutionPlanSchema.nullable().default(null),
  reason: z.string().nullable().default(null),
});
export type PlanApprovalRequest = z.infer<typeof PlanApprovalRequestSchema>;

export const PlanApprovalResponseSchema = z.object({
  execution_id: z.string().uuid(),
  decision: z.string(),
  new_status: ExecutionStatusSchema,
  message: z.string(),
});
export type PlanApprovalResponse = z.infer<typeof PlanApprovalResponseSchema>;

// ─── Escalation Resolution ─────────────────────────────────────────

export const EscalationResolutionRequestSchema = z.object({
  decision: z.enum(['continue', 'abort', 'retry', 'skip_step']),
  modified_step_params: z.record(z.unknown()).nullable().default(null),
  reason: z.string().nullable().default(null),
});
export type EscalationResolutionRequest = z.infer<typeof EscalationResolutionRequestSchema>;

// ─── WebSocket ─────────────────────────────────────────────────────

export const DAGNodeSchema = z.object({
  id: z.string(),
  type: z.string(),
  position: z.object({ x: z.number(), y: z.number() }),
  data: z.record(z.unknown()),
});
export type DAGNode = z.infer<typeof DAGNodeSchema>;

export const DAGEdgeSchema = z.object({
  id: z.string(),
  source: z.string(),
  target: z.string(),
  animated: z.boolean().default(false),
});
export type DAGEdge = z.infer<typeof DAGEdgeSchema>;

export const WebSocketMessageSchema = z.discriminatedUnion('type', [
  z.object({ type: z.literal('subscribe'), execution_id: z.string().uuid() }),
  z.object({ type: z.literal('unsubscribe'), execution_id: z.string().uuid() }),
  z.object({ type: z.literal('heartbeat') }),
]);
export type WebSocketMessage = z.infer<typeof WebSocketMessageSchema>;
