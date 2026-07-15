"""FastAPI dependencies for mcp-opsmate.

Provides injectable dependencies for config, database session,
MCP hub, state manager, and LLM client.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from opsmate.core.config import OpsMateConfig, get_config
from opsmate.infra.database import get_db_session
from opsmate.infra.llm import LLMClient, create_llm_client_from_config
from opsmate.infra.mcp_hub import MCPClientManager, ModeRouter, ToolRegistry
from opsmate.services.audit import AuditLogger
from opsmate.services.state import StateManager

logger: logging.Logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config dependency
# ---------------------------------------------------------------------------


async def get_config_dep() -> OpsMateConfig:
    """Get the global configuration."""
    return get_config()


# ---------------------------------------------------------------------------
# Database session dependency
# ---------------------------------------------------------------------------


async def get_db_session_dep() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session."""
    async for session in get_db_session():
        yield session


# ---------------------------------------------------------------------------
# State manager dependency
# ---------------------------------------------------------------------------


async def get_state_manager(
    db: AsyncSession = Depends(get_db_session_dep),
) -> StateManager:
    """Get a StateManager with database session."""
    manager: StateManager = StateManager(db)
    return manager


# ---------------------------------------------------------------------------
# Audit logger dependency
# ---------------------------------------------------------------------------


async def get_audit_logger() -> AuditLogger:
    """Get an AuditLogger instance."""
    from opsmate.core.config import get_config

    config: OpsMateConfig = get_config()
    return AuditLogger(level=config.logging.level)


# ---------------------------------------------------------------------------
# LLM client dependency
# ---------------------------------------------------------------------------


async def get_llm_client() -> LLMClient:
    """Get an LLMClient from configuration."""
    return create_llm_client_from_config()


# ---------------------------------------------------------------------------
# MCP Hub dependencies (from app state)
# ---------------------------------------------------------------------------


async def get_mcp_manager(request: Request) -> MCPClientManager:
    """Get the MCP client manager from app state."""
    manager: MCPClientManager | None = getattr(
        request.app.state, "mcp_manager", None
    )
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP Hub not initialized",
        )
    return manager


async def get_tool_registry(request: Request) -> ToolRegistry:
    """Get the tool registry from app state."""
    registry: ToolRegistry | None = getattr(
        request.app.state, "tool_registry", None
    )
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tool registry not initialized",
        )
    return registry


async def get_mode_router(request: Request) -> ModeRouter:
    """Get the mode router from app state."""
    router: ModeRouter | None = getattr(
        request.app.state, "mode_router", None
    )
    if router is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mode router not initialized",
        )
    return router
