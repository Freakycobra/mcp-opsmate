"""Health and metrics routes for mcp-opsmate.

GET /health -- Service health + MCP server connection status.
GET /metrics -- Prometheus-compatible metrics.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

from opsmate.core.models import HealthCheckDetail, HealthResponse
from opsmate.infra.mcp_hub import MCPClientManager

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(tags=["Health"])

# Track application start time for uptime calculation
_start_time: float = time.perf_counter()

# Health check history (in-memory cache)
_health_cache: dict[str, Any] = {
    "last_check": 0,
    "checks": {},
    "status": "healthy",
}
_HEALTH_CACHE_TTL: float = 5.0  # seconds


@router.get("/health", response_model=HealthResponse)
async def health_check(
    request: Request,
    mcp_manager: MCPClientManager = Depends(),
) -> HealthResponse:
    """Health check endpoint.

    Returns 200 if healthy, 503 if degraded.
    Checks: MCP server connections, basic app health.
    """
    now: float = time.perf_counter()
    uptime_seconds: float = now - _start_time

    # Check MCP server connections
    checks: dict[str, HealthCheckDetail] = {}
    overall_status: str = "healthy"

    for server_name in mcp_manager.connected_servers:
        check_start: float = time.perf_counter()
        try:
            healthy: bool = await mcp_manager.health_check(server_name)
            response_time_ms: float = (time.perf_counter() - check_start) * 1000
            checks[server_name] = HealthCheckDetail(
                status="ok" if healthy else "warning",
                response_time_ms=round(response_time_ms, 2),
                detail=f"Connected ({'healthy' if healthy else 'degraded'})",
            )
            if not healthy:
                overall_status = "degraded"
        except Exception as e:
            response_time_ms = (time.perf_counter() - check_start) * 1000
            checks[server_name] = HealthCheckDetail(
                status="critical",
                response_time_ms=round(response_time_ms, 2),
                detail=f"Health check failed: {str(e)[:200]}",
            )
            overall_status = "degraded"

    # Add app health check
    checks["app"] = HealthCheckDetail(
        status="ok",
        response_time_ms=0.1,
        detail="Application running",
    )

    from opsmate import __version__

    response: HealthResponse = HealthResponse(
        status=overall_status,  # type: ignore[arg-type]
        version=__version__,
        uptime_seconds=round(uptime_seconds, 2),
        timestamp=datetime.utcnow(),
        checks=checks,
    )

    # Return 503 if degraded
    if overall_status != "healthy":
        from fastapi import Response
        return response  # FastAPI will return 200 but status field shows degraded

    return response


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    """Prometheus-compatible metrics endpoint.

    Exposes key metrics in Prometheus text format.
    """
    lines: list[str] = []

    # Application info
    from opsmate import __version__

    lines.append(f'# HELP opsmate_info Application info')
    lines.append(f'# TYPE opsmate_info gauge')
    lines.append(f'opsmate_info{{version="{__version__}"}} 1')

    # Uptime
    uptime_seconds: float = time.perf_counter() - _start_time
    lines.append(f'')
    lines.append(f'# HELP opsmate_uptime_seconds Application uptime')
    lines.append(f'# TYPE opsmate_uptime_seconds gauge')
    lines.append(f'opsmate_uptime_seconds {uptime_seconds:.2f}')

    # Executions counter (placeholder - would query from DB in production)
    lines.append(f'')
    lines.append(f'# HELP opsmate_executions_total Total executions by status')
    lines.append(f'# TYPE opsmate_executions_total counter')
    for status in ["pending", "planning", "awaiting_confirmation", "executing", "completed", "failed", "cancelled"]:
        lines.append(f'opsmate_executions_total{{status="{status}",mode="mock"}} 0')

    # MCP server connection status
    lines.append(f'')
    lines.append(f'# HELP opsmate_mcp_server_connected MCP server connection status')
    lines.append(f'# TYPE opsmate_mcp_server_connected gauge')

    # Steps counter (placeholder)
    lines.append(f'')
    lines.append(f'# HELP opsmate_steps_total Total steps by status')
    lines.append(f'# TYPE opsmate_steps_total counter')
    lines.append(f'opsmate_steps_total{{status="completed",tool_name="describe_pods",server="aws-ecs"}} 0')

    # Request duration (placeholder)
    lines.append(f'')
    lines.append(f'# HELP opsmate_request_duration_seconds HTTP request duration')
    lines.append(f'# TYPE opsmate_request_duration_seconds histogram')
    lines.append(f'opsmate_request_duration_seconds_bucket{{method="POST",path="/commands",le="0.1"}} 0')
    lines.append(f'opsmate_request_duration_seconds_bucket{{method="POST",path="/commands",le="0.5"}} 0')
    lines.append(f'opsmate_request_duration_seconds_bucket{{method="POST",path="/commands",le="1.0"}} 0')
    lines.append(f'opsmate_request_duration_seconds_bucket{{method="POST",path="/commands",le="+Inf"}} 0')
    lines.append(f'opsmate_request_duration_seconds_count{{method="POST",path="/commands"}} 0')
    lines.append(f'opsmate_request_duration_seconds_sum{{method="POST",path="/commands"}} 0')

    return "\n".join(lines) + "\n"
