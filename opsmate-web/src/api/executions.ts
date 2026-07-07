import api from './client';
import {
  ExecutionListResponseSchema,
  ExecutionDetailSchema,
  PlanApprovalRequestSchema,
  PlanApprovalResponseSchema,
  EscalationResolutionRequestSchema,
} from '@/types/api';
import type {
  ExecutionListResponse,
  ExecutionDetail,
  PlanApprovalResponse,
  ExecutionStatus,
  ExecutionMode,
  EscalationResolutionRequest,
} from '@/types/api';

export interface ListExecutionsParams {
  page?: number;
  page_size?: number;
  status?: ExecutionStatus;
  mode?: ExecutionMode;
  from_date?: string;
  to_date?: string;
  command_q?: string;
  sort?: string;
}

/**
 * List executions with pagination and filtering.
 */
export async function listExecutions(
  params: ListExecutionsParams = {}
): Promise<ExecutionListResponse> {
  const response = await api.get('/executions', { params });
  return ExecutionListResponseSchema.parse(response.data);
}

/**
 * Get detailed execution state.
 */
export async function getExecution(id: string): Promise<ExecutionDetail> {
  const response = await api.get(`/executions/${id}`);
  return ExecutionDetailSchema.parse(response.data);
}

/**
 * Approve a pending execution plan.
 */
export async function approveExecution(id: string): Promise<PlanApprovalResponse> {
  const request = PlanApprovalRequestSchema.parse({ decision: 'approve' });
  const response = await api.post(`/executions/${id}/approve`, request);
  return PlanApprovalResponseSchema.parse(response.data);
}

/**
 * Reject a pending execution plan.
 */
export async function rejectExecution(
  id: string,
  reason?: string
): Promise<PlanApprovalResponse> {
  const request = PlanApprovalRequestSchema.parse({
    decision: 'reject',
    reason: reason ?? null,
  });
  const response = await api.post(`/executions/${id}/approve`, request);
  return PlanApprovalResponseSchema.parse(response.data);
}

/**
 * Resolve an escalation (human-in-the-loop).
 */
export async function resolveEscalation(
  id: string,
  resolution: EscalationResolutionRequest
): Promise<ExecutionDetail> {
  const validated = EscalationResolutionRequestSchema.parse(resolution);
  const response = await api.post(`/admin/executions/${id}/escalation`, validated);
  return ExecutionDetailSchema.parse(response.data);
}
