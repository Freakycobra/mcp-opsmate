"""FastAPI application factory for mcp-opsmate.

Handles app creation, lifespan events, router aggregation,
middleware registration, and MCP server initialization.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from opsmate import __version__
from opsmate.api.middleware.auth import APIKeyMiddleware
from opsmate.api.middleware.logging import LoggingMiddleware
from opsmate.api.routes import admin, commands, executions, health, stream
from opsmate.core.config import get_config
from opsmate.infra.database import close_db, init_db
from opsmate.infra.mcp_hub import create_mcp_hub

logger: logging.Logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan events.

    Startup:
    - Initialize database
    - Connect to MCP servers
    - Discover tools

    Shutdown:
    - Disconnect from MCP servers
    - Close database connections
    """
    config = get_config()
    logger.info(
        "Starting mcp-opsmate v%s (mode=%s)",
        __version__,
        config.app.execution_mode,
    )

    # Initialize database
    try:
        await init_db(database_url=config.database.url)
        logger.info("Database initialized")
    except Exception as e:
        logger.error("Database initialization failed: %s", e)
        # Continue without database - some operations may fail

    # Initialize MCP Hub
    try:
        manager, registry, router = await create_mcp_hub()
        app.state.mcp_manager = manager
        app.state.tool_registry = registry
        app.state.mode_router = router
        logger.info(
            "MCP Hub initialized: %d servers, %d tools",
            manager.server_count,
            registry.tool_count,
        )
    except Exception as e:
        logger.error("MCP Hub initialization failed: %s", e)
        # Create empty hub for graceful degradation
        from opsmate.infra.mcp_hub import MCPClientManager, ModeRouter, ToolRegistry

        empty_manager: MCPClientManager = MCPClientManager()
        empty_registry: ToolRegistry = ToolRegistry(empty_manager)
        empty_router: ModeRouter = ModeRouter(empty_manager)
        app.state.mcp_manager = empty_manager
        app.state.tool_registry = empty_registry
        app.state.mode_router = empty_router

    yield

    # Shutdown
    logger.info("Shutting down mcp-opsmate...")

    # Disconnect MCP servers
    try:
        manager = getattr(app.state, "mcp_manager", None)
        if manager:
            await manager.disconnect_all()
            logger.info("MCP servers disconnected")
    except Exception as e:
        logger.error("MCP disconnect error: %s", e)

    # Close database
    try:
        await close_db()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error("Database close error: %s", e)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI app with all routers and middleware.
    """
    app: FastAPI = FastAPI(
        title="mcp-opsmate",
        description="Infrastructure Automation MCP Terminal",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Register middleware (order matters: auth runs last = executes first on request)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(APIKeyMiddleware)

    # Register routers
    app.include_router(health.router)
    app.include_router(commands.router)
    app.include_router(executions.router)
    app.include_router(stream.router)
    app.include_router(admin.router)

    # Add startup health check endpoint at root
    @app.get("/", tags=["Root"])
    async def root() -> dict[str, str]:
        """Root endpoint for health verification."""
        return {
            "service": "mcp-opsmate",
            "version": __version__,
            "status": "running",
        }

    @app.get("/examples", tags=["Examples"])
    async def examples() -> dict[str, list[dict[str, str]]]:
        """Built-in demo commands for zero-config onboarding."""
        from opsmate.core.models import DemoCommand, ExamplesResponse

        demo_commands: list[DemoCommand] = [
            DemoCommand(
                title="Health Check & Remediate",
                description="Check pod health and restart if CPU exceeds threshold",
                command="Check payment-service pods in EKS, restart if CPU > 80%",
                expected_plan_template="health-check-and-remediate",
                category="health",
            ),
            DemoCommand(
                title="Incident Response",
                description="Find incidents and create incident tickets",
                command="Find P0 incidents in JIRA from last 24h and post summary to #incidents",
                expected_plan_template="incident-response",
                category="incident",
            ),
            DemoCommand(
                title="Deployment Validation",
                description="Verify deployment health after release",
                command="Verify the deployment of api-gateway v2.1.0",
                expected_plan_template="deployment-validation",
                category="health",
            ),
            DemoCommand(
                title="Performance Analysis",
                description="Compare metrics across services",
                command="Compare Lambda costs between us-east-1 and eu-west-1 for the last 7 days",
                expected_plan_template="performance-analysis",
                category="analysis",
            ),
            DemoCommand(
                title="CI Correlation",
                description="Connect CI failures to incident tickets",
                command="Correlate the failed GitHub workflow with any JIRA tickets and Slack alerts",
                expected_plan_template="incident-response",
                category="correlation",
            ),
        ]

        return ExamplesResponse(examples=demo_commands).model_dump()

    logger.info(
        "FastAPI app created with %d routers",
        len(app.routes),
    )
    return app


# Singleton app instance
_app: FastAPI | None = None


def get_app() -> FastAPI:
    """Get or create the global FastAPI app singleton."""
    global _app
    if _app is None:
        _app = create_app()
    return _app
