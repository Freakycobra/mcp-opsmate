import api from './client';
import {
  ModeConfigurationResponseSchema,
  ModeSwitchRequestSchema,
  ModeSwitchResponseSchema,
  HealthResponseSchema,
  ToolRegistryResponseSchema,
  ToolRefreshResponseSchema,
} from '@/types/api';
import type {
  ModeConfigurationResponse,
  ModeSwitchRequest,
  ModeSwitchResponse,
  HealthResponse,
  ToolRegistryResponse,
  ToolRefreshResponse,
  ExecutionMode,
} from '@/types/api';

/**
 * Get current execution mode configuration.
 */
export async function getMode(): Promise<ModeConfigurationResponse> {
  const response = await api.get('/admin/mode');
  return ModeConfigurationResponseSchema.parse(response.data);
}

/**
 * Switch execution mode.
 */
export async function setMode(
  mode: ExecutionMode,
  reason: string,
  options: {
    serverOverrides?: Record<string, 'mock' | 'live' | 'local'>;
    force?: boolean;
  } = {}
): Promise<ModeSwitchResponse> {
  const request: ModeSwitchRequest = {
    global_mode: mode,
    server_overrides: options.serverOverrides ?? {},
    reason,
    force: options.force ?? false,
  };

  const validated = ModeSwitchRequestSchema.parse(request);
  const response = await api.post('/admin/mode', validated);
  return ModeSwitchResponseSchema.parse(response.data);
}

/**
 * Get health check status.
 */
export async function getHealth(): Promise<HealthResponse> {
  const response = await api.get('/health');
  return HealthResponseSchema.parse(response.data);
}

/**
 * List available MCP tools from the registry.
 */
export async function listTools(): Promise<ToolRegistryResponse> {
  const response = await api.get('/admin/tools');
  return ToolRegistryResponseSchema.parse(response.data);
}

/**
 * Refresh the tool registry (re-discover all MCP tools).
 */
export async function refreshTools(): Promise<ToolRefreshResponse> {
  const response = await api.post('/admin/tools/refresh');
  return ToolRefreshResponseSchema.parse(response.data);
}
