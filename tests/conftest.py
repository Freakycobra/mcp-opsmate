"""
Shared pytest fixtures for the mcp-opsmate test suite.

All fixtures are async-compatible and use pytest-asyncio.
External APIs (OpenAI, Tavily, etc.) are fully mocked — no real API calls.
The mock_mcp_hub fixture provides a test-local MCP hub with 3 mock servers.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

# ── Test Database Fixtures ──────────────────────────────────────────


@pytest_asyncio.fixture(scope="session")
def event_loop() -> asyncio.AbstractEventLoop:
    """Create a dedicated event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_db() -> AsyncGenerator[dict[str, str], None]:
    """Set up and tear down a test database instance.

    Creates a unique test database for each test session to ensure
    complete isolation. Drops the database after the session completes.
    """
    test_db_name = f"opsmate_test_{uuid.uuid4().hex[:8]}"
    db_url = f"postgresql+asyncpg://opsmate:opsmate@localhost:5432/{test_db_name}"

    # Create the test database
    admin_url = "postgresql+asyncpg://opsmate:opsmate@localhost:5432/postgres"
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(f"CREATE DATABASE {test_db_name}")
    await admin_engine.dispose()

    # Run migrations
    engine = create_async_engine(db_url)
    from opsmate.infra.database import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    yield {"db_name": test_db_name, "db_url": db_url}

    # Cleanup: drop the test database
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        # Terminate any remaining connections
        await conn.execute(
            f"""
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = '{test_db_name}' AND pid <> pg_backend_pid()
            """
        )
        await conn.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
    await admin_engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_db: dict[str, str]) -> AsyncGenerator[Any, None]:
    """Provide an async database session for a single test.

    Automatically rolls back all changes after the test completes,
    ensuring test isolation.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(test_db["db_url"])
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        yield session

    await engine.dispose()


# ── FastAPI Test Client ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_app(
    test_db: dict[str, str],
    mock_mcp_hub: Any,
) -> AsyncGenerator[FastAPI, None]:
    """Create a configured FastAPI app with mocked dependencies."""
    from opsmate.api.main import create_app
    from opsmate.core.config import get_settings
    from opsmate.infra.database import get_db_session
    from opsmate.infra.mcp_hub import get_mcp_hub

    # Override settings for tests
    test_settings = get_settings()
    test_settings.database_url = test_db["db_url"]
    test_settings.execution_mode = "mock"
    test_settings.api_key = "test-api-key"
    test_settings.admin_api_token = "test-admin-token"
    test_settings.openai_api_key = "test-openai-key"
    test_settings.redis_url = "redis://localhost:6379/9"  # Use DB 9 for tests

    app = create_app(settings=test_settings)

    # Override dependencies with mocks
    app.dependency_overrides[get_mcp_hub] = lambda: mock_mcp_hub

    # Database session override
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    test_engine = create_async_engine(test_db["db_url"])
    test_session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with test_session_maker() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db

    yield app

    await test_engine.dispose()


@pytest_asyncio.fixture
async def test_client(test_app: FastAPI) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide an async HTTP client for testing FastAPI endpoints."""
    from httpx import ASGITransport

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ── Mock MCP Hub ────────────────────────────────────────────────────


class MockMCPServer:
    """A mock MCP server for testing."""

    def __init__(self, name: str, tools: list[dict[str, Any]]) -> None:
        self.name = name
        self.tools = tools
        self.connected = True
        self.mode = "mock"
        self.call_count = 0

    async def list_tools(self) -> list[dict[str, Any]]:
        return self.tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.call_count += 1
        return {
            "tool": tool_name,
            "server": self.name,
            "arguments": arguments,
            "result": f"mock-result-from-{self.name}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@pytest_asyncio.fixture
async def mock_mcp_hub() -> MagicMock:
    """Provide a mock MCP hub with 3 mock servers for isolated testing.

    Returns a MagicMock that simulates the MCPClientManager with:
    - tavily-search: search tools
    - github: repository tools
    - calculator: math tools

    No real MCP server processes are started.
    """
    hub = MagicMock()

    # Create 3 mock servers with representative tools
    tavily_tools = [
        {"name": "search", "description": "Search the web", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}},
        {"name": "search_news", "description": "Search news", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}},
    ]
    github_tools = [
        {"name": "get_repo", "description": "Get repository info", "input_schema": {"type": "object", "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}}}},
        {"name": "list_issues", "description": "List repository issues", "input_schema": {"type": "object", "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}, "state": {"type": "string"}}}},
        {"name": "get_workflow_runs", "description": "Get workflow runs", "input_schema": {"type": "object", "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}}}},
    ]
    calculator_tools = [
        {"name": "calculate", "description": "Perform calculation", "input_schema": {"type": "object", "properties": {"expression": {"type": "string"}}}},
        {"name": "evaluate_expression", "description": "Evaluate math expression", "input_schema": {"type": "object", "properties": {"expression": {"type": "string"}}}},
    ]

    servers = {
        "tavily-search": MockMCPServer("tavily-search", tavily_tools),
        "github": MockMCPServer("github", github_tools),
        "calculator": MockMCPServer("calculator", calculator_tools),
    }

    hub.servers = servers
    hub.get_server = MagicMock(side_effect=lambda name: servers.get(name))
    hub.list_servers = MagicMock(return_value=list(servers.keys()))
    hub.list_all_tools = AsyncMock(return_value=[
        {**tool, "server": name}
        for name, server in servers.items()
        for tool in server.tools
    ])
    hub.call_tool = AsyncMock(side_effect=_mock_call_tool(servers))
    hub.get_server_status = MagicMock(return_value={
        name: {"connected": s.connected, "mode": s.mode, "tool_count": len(s.tools)}
        for name, s in servers.items()
    })
    hub.refresh_tools = AsyncMock(return_value={"refreshed": True, "tool_count": 7})

    return hub


def _mock_call_tool(
    servers: dict[str, MockMCPServer],
) -> Callable[..., Any]:
    """Create a mock call_tool function that routes to the appropriate server."""
    async def _call(server_name: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        server = servers.get(server_name)
        if not server:
            raise ValueError(f"Unknown MCP server: {server_name}")
        if not server.connected:
            raise ConnectionError(f"MCP server {server_name} is disconnected")
        return await server.call_tool(tool_name, arguments)
    return _call


# ── Sample Data Fixtures ────────────────────────────────────────────


@pytest.fixture
def sample_intent() -> dict[str, Any]:
    """Return a sample intent classification result."""
    return {
        "type": ["QUERY", "ACTION"],
        "entities": {
            "service_name": "payment-service",
            "cluster": "eks-production",
            "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-01-01T02:00:00Z"},
            "threshold": {"operator": ">", "value": 80.0, "metric": "cpu_percent"},
            "notification_target": {"type": "slack", "channel": "on-call"},
        },
        "confidence": 0.94,
        "plan_template": "health-check-and-remediate",
    }


@pytest.fixture
def sample_plan() -> dict[str, Any]:
    """Return a sample execution plan (DAG)."""
    return {
        "execution_id": str(uuid.uuid4()),
        "steps": [
            {
                "id": "step-1",
                "tool_name": "describe_pods",
                "server": "aws-ecs",
                "description": "List pods for payment-service in EKS",
                "input_schema": {"service": "payment-service", "cluster": "eks-production"},
                "output_schema": {"type": "array", "items": {"type": "object"}},
                "critical": False,
                "condition": None,
            },
            {
                "id": "step-2",
                "tool_name": "get_cloudwatch_metrics",
                "server": "aws-ecs",
                "description": "Get CPU metrics for payment-service pods",
                "input_schema": {"service": "payment-service", "metric": "CPUUtilization", "duration": "2h"},
                "output_schema": {"type": "object"},
                "critical": False,
                "condition": None,
            },
            {
                "id": "step-3",
                "tool_name": "restart_pods",
                "server": "aws-ecs",
                "description": "Restart pods with CPU > 80%",
                "input_schema": {"pod_ids": "{{step-1.output.pod_ids}}", "threshold": 80},
                "output_schema": {"type": "object"},
                "critical": True,
                "condition": "{{step-2.output.max_cpu}} > 80",
            },
            {
                "id": "step-4",
                "tool_name": "send_slack_message",
                "server": "slack",
                "description": "Notify on-call Slack channel",
                "input_schema": {"channel": "on-call", "message": "Payment-service remediation complete"},
                "output_schema": {"type": "object"},
                "critical": False,
                "condition": None,
            },
        ],
        "dependencies": {
            "step-1": ["step-2", "step-3"],
            "step-2": ["step-3"],
            "step-3": ["step-4"],
            "step-4": [],
        },
        "estimated_duration_ms": 15000,
        "risk_level": "MEDIUM",
    }


@pytest.fixture
def sample_state(sample_plan: dict[str, Any]) -> dict[str, Any]:
    """Return a sample execution state."""
    exec_id = uuid.uuid4()
    return {
        "execution_id": exec_id,
        "status": "completed",
        "command_text": "Check payment-service pods in EKS, restart if CPU > 80%, alert Slack",
        "execution_mode": "mock",
        "plan": sample_plan,
        "results": {
            "step-1": {
                "step_id": "step-1",
                "status": "completed",
                "output": {"pods": [{"name": "pod-1", "status": "Running", "cpu": 45.2}]},
                "started_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            },
            "step-2": {
                "step_id": "step-2",
                "status": "completed",
                "output": {"max_cpu": 87.5, "avg_cpu": 62.3},
                "started_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            },
            "step-3": {
                "step_id": "step-3",
                "status": "completed",
                "output": {"restarted": ["pod-3", "pod-7"]},
                "started_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            },
            "step-4": {
                "step_id": "step-4",
                "status": "completed",
                "output": {"message_id": "msg_12345", "channel": "on-call"},
                "started_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            },
        },
        "context": {
            "variables": {"service_name": "payment-service", "threshold": 80},
            "metadata": {},
            "secrets_redacted": True,
        },
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "completed_at": datetime.now(timezone.utc),
        "planning_duration_ms": 450.2,
        "total_duration_ms": 1830.5,
    }


# ── Authentication Helpers ──────────────────────────────────────────


@pytest.fixture
def api_headers() -> dict[str, str]:
    """Return standard API authentication headers."""
    return {"X-API-Key": "test-api-key"}


@pytest.fixture
def admin_headers() -> dict[str, str]:
    """Return admin authentication headers."""
    return {
        "Authorization": "Bearer test-admin-token",
        "X-API-Key": "test-api-key",
    }


# ── Mock External APIs ──────────────────────────────────────────────


@pytest.fixture
def mock_openai() -> MagicMock:
    """Mock the OpenAI client to avoid real API calls."""
    with patch("opsmate.infra.llm.AsyncOpenAI") as mock_client:
        mock_chat = MagicMock()
        mock_chat.completions.create = AsyncMock(return_value=MagicMock(
            choices=[MagicMock(
                message=MagicMock(
                    content='{"type": ["QUERY"], "entities": {"service_name": "payment-service"}, "confidence": 0.92}'
                )
            )]
        ))
        mock_client.return_value.chat = mock_chat
        yield mock_client


@pytest.fixture
def mock_tavily() -> MagicMock:
    """Mock Tavily API calls."""
    with patch("opsmate.mcp_servers.tavily.tavily_client") as mock:
        mock.search = AsyncMock(return_value={
            "results": [{"title": "Mock result", "url": "https://example.com", "content": "Mock content"}]
        })
        yield mock
