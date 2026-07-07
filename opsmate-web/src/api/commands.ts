import api from './client';
import {
  CommandRequestSchema,
  CommandResponseSchema,
  ExamplesResponseSchema,
} from '@/types/api';
import type { CommandRequest, CommandResponse, ExamplesResponse } from '@/types/api';

/**
 * Submit a natural language command to the orchestrator.
 */
export async function submitCommand(
  text: string,
  options: {
    autoApprove?: boolean;
    modeOverride?: 'mock' | 'live' | 'mixed' | null;
    metadata?: Record<string, unknown>;
  } = {}
): Promise<CommandResponse> {
  const request: CommandRequest = {
    text,
    auto_approve: options.autoApprove ?? false,
    execution_mode_override: options.modeOverride ?? null,
    metadata: options.metadata ?? {},
  };

  const validatedRequest = CommandRequestSchema.parse(request);
  const response = await api.post('/commands', validatedRequest);
  return CommandResponseSchema.parse(response.data);
}

/**
 * Get the list of demo/example commands.
 */
export async function getExamples(): Promise<ExamplesResponse> {
  const response = await api.get('/examples');
  return ExamplesResponseSchema.parse(response.data);
}

/**
 * Get the SSE stream URL for an execution.
 * Note: API key is appended as query param since SSE headers are limited.
 */
export function getStreamUrl(executionId: string): string {
  const apiKey = localStorage.getItem('opsmate_api_key') || '';
  const baseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
  return `${baseUrl}/stream/${executionId}?api_key=${encodeURIComponent(apiKey)}`;
}
