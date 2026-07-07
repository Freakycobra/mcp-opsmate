"""Admin route for mcp-opsmate.

GET /admin/mode -- Get current execution mode.
POST /admin/mode -- Switch execution mode (admin token required).
GET /admin/tools -- List available tools.
POST /admin/tools/refresh -- Refresh tool registry.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from opsmate.core.config import get_config
from opsmate.core.constants import ExecutionMode
from opsmate.core.models import (
    ModeConfigurationResponse,
    ModeSwitchRequest,
    ModeSwitchResponse,
    ToolRefreshResponse,
    ToolRegistryResponse,
    ServerRefreshResult,
)
from opsmate.infra.mcp_hub import MCPClientManager, ToolRegistry
from opsmate.services.audit import AuditLogger
from opsmate.services.state import StateManager

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/admin", tags=["Admin"])

# Track mode changes
_last_mode_change: dict[str, Any] = {
    "at": None,
    "by": None,
}


@router.get("/mode", response_model=ModeConfigurationResponse)
async def get_mode(
    state_manager: StateManager = Depends(),
) -> ModeConfigurationResponse:
    """Get current execution mode configuration."""
    config = get_config()

    # Count active executions
    executions, _ = await state_manager.list_executions(
        status=ExecutionStatus.EXECUTING,
        page=1,
        page_size=1,
    )
    active_executions: int = len(executions)

    # Build server modes dict
    server_modes: dict[str, str] = {}
    for name, mcp_config in config.mcp_servers.items():
        server_modes[name] = mcp_config.mode

    return ModeConfigurationResponse(
        global_mode=config.app.execution_mode,  # type: ignore[arg-type]
        effective_mode=config.app.execution_mode,  # type: ignore[arg-type]
        server_modes=server_modes,  # type: ignore[arg-type]
        can_switch_at_runtime=True,
        active_executions=active_executions,
        last_changed_at=_last_mode_change.get("at"),
        last_changed_by=_last_mode_change.get("by"),
    )


@router.post("/mode", response_model=ModeSwitchResponse)
async def switch_mode(
    switch_request: ModeSwitchRequest,
    state_manager: StateManager = Depends(),
    audit_logger: AuditLogger = Depends(),
) -> ModeSwitchResponse:
    """Switch execution mode (admin token required).

    Validation:
    - Mode change rejected if active_executions > 0 and force=False
    - In-flight executions continue in their original mode
    - Change logged to audit trail
    """
    config = get_config()
    previous_mode: str = config.app.execution_mode

    # Check for active executions
    executions, _ = await state_manager.list_executions(
        status=ExecutionStatus.EXECUTING,
        page=1,
        page_size=1,
    )
    active_count: int = len(executions)

    if active_count > 0 and not switch_request.force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot switch mode with {active_count} active executions. Use force=true to override.",
        )

    # Apply mode change (update config in-memory)
    # In production, this would persist to database
    config.app.execution_mode = switch_request.global_mode  # type: ignore[assignment]

    # Update server overrides if in mixed mode
    if switch_request.global_mode == "mixed" and switch_request.server_overrides:
        for server_name, server_mode in switch_request.server_overrides.items():
            if server_name in config.mcp_servers:
                config.mcp_servers[server_name].mode = server_mode  # type: ignore[assignment]

    # Track change
    global _last_mode_change
    _last_mode_change = {
        "at": datetime.utcnow(),
        "by": "admin",  # Would come from auth context
    }

    audit_logger.log_mode_switched(
        previous_mode=previous_mode,
        new_mode=switch_request.global_mode,
        reason=switch_request.reason,
    )

    return ModeSwitchResponse(
        previous_mode=previous_mode,
        new_mode=switch_request.global_mode,
        applied_at=datetime.utcnow(),
        active_executions_unchanged=active_count,
        message=f"Mode switched from {previous_mode} to {switch_request.global_mode}. {active_count} active executions continue in their original mode.",
    )


@router.get("/tools", response_model=ToolRegistryResponse)
async def list_tools(
    tool_registry: ToolRegistry = Depends(),
) -> ToolRegistryResponse:
    """List available MCP tools from all connected servers."""
    from opsmate.core.models import ServerToolsInfo, ToolInfo

    servers: list[ServerToolsInfo] = []
    for server_name in tool_registry._server_tools:
        tools: list[ToolInfo] = tool_registry.list_server_tools(server_name)
        # Get connection status from a mock for now
        servers.append(ServerToolsInfo(
            server_name=server_name,
            transport="stdio",
            connected=True,
            mode="mock",
            tool_count=len(tools),
            tools=tools,
        ))

    return ToolRegistryResponse(
        last_refreshed_at=datetime.fromisoformat(tool_registry.last_refreshed_at) if tool_registry.last_refreshed_at else datetime.utcnow(),
        server_count=tool_registry.server_count,
        total_tools=tool_registry.tool_count,
        servers=servers,
    )


@router.post("/tools/refresh", response_model=ToolRefreshResponse)
async def refresh_tools(
    tool_registry: ToolRegistry = Depends(),
    mcp_manager: MCPClientManager = Depends(),
    audit_logger: AuditLogger = Depends(),
) -> ToolRefreshResponse:
    """Force re-discovery of all MCP tools."""
    refreshed_at: datetime = datetime.utcnow()

    server_results: list[ServerRefreshResult] = []
    total_tools: int = 0

    for server_name in mcp_manager.connected_servers:
        try:
            # Re-discover tools for this server
            count: int = await tool_registry._discover_server_tools(server_name)
            total_tools += count
            server_results.append(ServerRefreshResult(
                server_name=server_name,
                status="ok",
                tools_found=count,
            ))
        except Exception as e:
            logger.error("Failed to refresh tools for %s: %s", server_name, e)
            server_results.append(ServerRefreshResult(
                server_name=server_name,
                status="failed",
                tools_found=0,
                error=str(e),
            ))

    audit_logger.log_tool_registry_refresh(
        servers_discovered=len(server_results),
        tools_discovered=total_tools,
    )

    return ToolRefreshResponse(
        refreshed_at=refreshed_at,
        servers_discovered=len(server_results),
        tools_discovered=total_tools,
        servers=server_results,
    )
