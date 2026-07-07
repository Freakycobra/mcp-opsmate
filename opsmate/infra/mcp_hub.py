"""MCP Server Hub for mcp-opsmate.

Contains three core classes:
- MCPClientManager: Manages MCP client connections via stdio transport
- ToolRegistry: Discovers and caches tools from all connected MCP servers
- ModeRouter: Resolves execution mode per MCP server and routes accordingly
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import Any, Callable, Coroutine, Literal

from opsmate.core.config import get_config
from opsmate.core.constants import MCP_HEALTH_CHECK_INTERVAL, MCP_RECONNECT_MAX_ATTEMPTS
from opsmate.core.exceptions import CircuitBreakerOpenError, MCPToolNotFoundError
from opsmate.core.models import ToolInfo
from opsmate.infra.mock_factory import MockFactory

logger: logging.Logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MCPClientManager -- manages stdio MCP client connections
# ---------------------------------------------------------------------------


class MCPClientManager:
    """Manages MCP client connections using stdio transport.

    Handles lifecycle: connect -> discover_tools -> health_check -> disconnect.
    Supports reconnection with exponential backoff and periodic health checks.
    """

    def __init__(
        self,
        server_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._configs: dict[str, dict[str, Any]] = server_configs or {}
        self._connections: dict[str, Any] = {}
        self._connected: dict[str, bool] = {}
        self._tool_cache: dict[str, list[dict[str, Any]]] = {}
        self._health_check_tasks: dict[str, asyncio.Task] = {}
        self._reconnect_attempts: dict[str, int] = {}

    @property
    def connected_servers(self) -> list[str]:
        """List of currently connected server names."""
        return [name for name, connected in self._connected.items() if connected]

    @property
    def server_count(self) -> int:
        """Total number of configured servers."""
        return len(self._configs)

    def is_connected(self, server_name: str) -> bool:
        """Check if a specific server is connected."""
        return self._connected.get(server_name, False)

    async def connect_all(self) -> dict[str, bool]:
        """Connect to all configured MCP servers.

        Returns:
            Dict mapping server name to connection success.
        """
        results: dict[str, bool] = {}
        async with asyncio.TaskGroup() as tg:
            tasks: dict[str, asyncio.Task] = {}
            for name, config in self._configs.items():
                tasks[name] = tg.create_task(self._connect_server(name, config))
        for name, task in tasks.items():
            try:
                results[name] = task.result()
            except Exception as e:
                logger.error("Connection to %s failed: %s", name, e)
                results[name] = False
        return results

    async def _connect_server(self, name: str, config: dict[str, Any]) -> bool:
        """Connect to a single MCP server.

        Uses stdio transport with subprocess. Simulates connection by
        storing configuration and verifying command is set.
        """
        try:
            transport: str = config.get("transport", "stdio")
            command: list[str] | None = config.get("command")

            if transport == "stdio" and not command:
                logger.error("Server %s: stdio transport requires command list", name)
                return False

            # In a real implementation, this would use mcp.ClientSession
            # with stdio_server transport. Here we simulate the connection
            # by verifying the server module can be imported.
            self._connections[name] = {
                "transport": transport,
                "command": command,
                "config": config,
                "connected_at": asyncio.get_event_loop().time(),
            }
            self._connected[name] = True
            self._reconnect_attempts[name] = 0
            logger.info("Connected to MCP server: %s (transport=%s)", name, transport)

            # Start health check loop
            self._start_health_check(name)
            return True

        except Exception as e:
            logger.error("Failed to connect to MCP server %s: %s", name, e)
            self._connected[name] = False
            return False

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers gracefully."""
        for name in list(self._health_check_tasks.keys()):
            self._stop_health_check(name)

        for name in list(self._connections.keys()):
            await self._disconnect_server(name)

        self._connections.clear()
        self._connected.clear()
        logger.info("All MCP servers disconnected")

    async def _disconnect_server(self, name: str) -> None:
        """Disconnect from a single MCP server."""
        self._stop_health_check(name)
        self._connected[name] = False
        if name in self._connections:
            del self._connections[name]
        logger.info("Disconnected from MCP server: %s", name)

    async def health_check(self, server_name: str) -> bool:
        """Perform a health check on a specific MCP server.

        Simulated by checking connection state. In production, this would
        call mcp.list_tools() to verify the server is responsive.
        """
        if not self._connected.get(server_name, False):
            return False

        # Simulate health check latency
        await asyncio.sleep(0.01)

        # For the calculator server (always local), always healthy
        if server_name == "calculator":
            return True

        # Random health check failure simulation (1% chance)
        import random

        if random.random() < 0.01:
            logger.warning("Health check failed for %s (simulated)", server_name)
            self._connected[server_name] = False
            return False

        return True

    def _start_health_check(self, server_name: str) -> None:
        """Start periodic health check for a server."""
        if server_name in self._health_check_tasks:
            return

        async def _health_loop() -> None:
            while True:
                try:
                    await asyncio.sleep(MCP_HEALTH_CHECK_INTERVAL)
                    healthy: bool = await self.health_check(server_name)
                    if not healthy:
                        logger.warning("Health check failed for %s, triggering reconnect", server_name)
                        await self._attempt_reconnect(server_name)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.exception("Health check error for %s: %s", server_name, e)

        self._health_check_tasks[server_name] = asyncio.create_task(
            _health_loop(), name=f"health-check-{server_name}"
        )

    def _stop_health_check(self, server_name: str) -> None:
        """Stop health check loop for a server."""
        task: asyncio.Task | None = self._health_check_tasks.pop(server_name, None)
        if task and not task.done():
            task.cancel()

    async def _attempt_reconnect(self, server_name: str) -> bool:
        """Attempt to reconnect to a server with exponential backoff."""
        attempts: int = self._reconnect_attempts.get(server_name, 0)
        if attempts >= MCP_RECONNECT_MAX_ATTEMPTS:
            logger.error(
                "Max reconnection attempts (%d) reached for %s",
                MCP_RECONNECT_MAX_ATTEMPTS,
                server_name,
            )
            return False

        backoff: float = min(2 ** attempts, 60)  # cap at 60s
        logger.info(
            "Reconnecting to %s in %.1fs (attempt %d/%d)",
            server_name,
            backoff,
            attempts + 1,
            MCP_RECONNECT_MAX_ATTEMPTS,
        )
        await asyncio.sleep(backoff)

        config: dict[str, Any] = self._configs.get(server_name, {})
        success: bool = await self._connect_server(server_name, config)
        if success:
            self._reconnect_attempts[server_name] = 0
            return True
        else:
            self._reconnect_attempts[server_name] = attempts + 1
            return False

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Call a tool on a connected MCP server.

        Args:
            server_name: The MCP server name.
            tool_name: The tool to call.
            arguments: Tool arguments.

        Returns:
            Tool call result.

        Raises:
            MCPToolNotFoundError: If the server is not connected.
        """
        if not self.is_connected(server_name):
            raise MCPToolNotFoundError(
                tool_name=f"{server_name}/{tool_name}",
                available_tools=self.list_all_tools(),
            )

        # In a real implementation, this would use mcp.ClientSession.call_tool()
        # Here we return a placeholder that the ModeRouter will override
        logger.debug("Live tool call: %s/%s", server_name, tool_name)
        return {"_mode": "live", "server": server_name, "tool": tool_name, "args": arguments}

    def list_all_tools(self) -> list[str]:
        """List all available tools from all connected servers."""
        tools: list[str] = []
        for server_name, tool_list in self._tool_cache.items():
            for tool in tool_list:
                tool_name: str = tool.get("name", "unknown")
                tools.append(f"{server_name}/{tool_name}")
        return tools

    def cache_tools(self, server_name: str, tools: list[dict[str, Any]]) -> None:
        """Cache discovered tools for a server."""
        self._tool_cache[server_name] = tools


# ---------------------------------------------------------------------------
# ToolRegistry -- discovers and caches tools from all connected MCP servers
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Discovers all tools from connected MCP servers.

    Caches tool schemas with name, description, input_schema, output_schema,
    and server_source. Supports lookup by name with server prefix disambiguation.
    """

    def __init__(self, client_manager: MCPClientManager) -> None:
        self._manager: MCPClientManager = client_manager
        self._tools: dict[str, ToolInfo] = {}
        self._server_tools: dict[str, list[str]] = {}
        self._last_refreshed: str = ""

    @property
    def tool_count(self) -> int:
        """Total number of registered tools."""
        return len(self._tools)

    @property
    def server_count(self) -> int:
        """Number of servers with registered tools."""
        return len(self._server_tools)

    @property
    def last_refreshed_at(self) -> str:
        """ISO timestamp of last refresh."""
        return self._last_refreshed

    async def discover_all(self) -> int:
        """Discover tools from all connected MCP servers.

        Returns:
            Total number of tools discovered.
        """
        from datetime import datetime

        total: int = 0
        self._tools.clear()
        self._server_tools.clear()

        for server_name in self._manager.connected_servers:
            count: int = await self._discover_server_tools(server_name)
            total += count

        self._last_refreshed = datetime.utcnow().isoformat()
        logger.info("Tool registry refreshed: %d tools from %d servers", total, self.server_count)
        return total

    async def _discover_server_tools(self, server_name: str) -> int:
        """Discover tools from a single server.

        In a real implementation, this would call mcp.list_tools() via
        the client session. Here we use static tool definitions.
        """
        # Static tool definitions for all 7 servers
        tool_definitions: dict[str, list[dict[str, Any]]] = {
            "tavily-search": [
                {
                    "name": "search",
                    "description": "Perform web search via Tavily API",
                    "input_schema": {"query": "string", "max_results": "int"},
                    "destructive": False,
                },
                {
                    "name": "answer",
                    "description": "Search and synthesize an answer with sources",
                    "input_schema": {"query": "string", "include_sources": "bool"},
                    "destructive": False,
                },
            ],
            "github": [
                {
                    "name": "repo_info",
                    "description": "Get GitHub repository information",
                    "input_schema": {"owner": "string", "repo": "string"},
                    "destructive": False,
                },
                {
                    "name": "workflow_status",
                    "description": "Get GitHub Actions workflow status",
                    "input_schema": {"owner": "string", "repo": "string", "branch": "string"},
                    "destructive": False,
                },
                {
                    "name": "pr_checks",
                    "description": "Get PR check runs",
                    "input_schema": {"owner": "string", "repo": "string", "pr_number": "int"},
                    "destructive": False,
                },
            ],
            "slack": [
                {
                    "name": "send_message",
                    "description": "Send a message to a Slack channel",
                    "input_schema": {"channel": "string", "text": "string", "thread_ts": "string?"},
                    "destructive": True,
                },
            ],
            "jira": [
                {
                    "name": "search_tickets",
                    "description": "Search Jira tickets using JQL",
                    "input_schema": {"jql": "string", "max_results": "int"},
                    "destructive": False,
                },
                {
                    "name": "create_incident",
                    "description": "Create a Jira incident ticket",
                    "input_schema": {
                        "summary": "string",
                        "description": "string",
                        "priority": "string",
                        "labels": "string[]",
                    },
                    "destructive": True,
                },
            ],
            "aws-ecs": [
                {
                    "name": "describe_pods",
                    "description": "Describe ECS/EKS pods for a service",
                    "input_schema": {"namespace": "string", "service": "string"},
                    "destructive": False,
                },
                {
                    "name": "get_metrics",
                    "description": "Get CloudWatch metrics",
                    "input_schema": {
                        "namespace": "string",
                        "service": "string",
                        "metric": "string",
                        "duration_minutes": "int",
                    },
                    "destructive": False,
                },
                {
                    "name": "restart_pod",
                    "description": "Restart an ECS/EKS pod",
                    "input_schema": {"namespace": "string", "pod_name": "string", "graceful": "bool"},
                    "destructive": True,
                },
            ],
            "postgres-db": [
                {
                    "name": "execute_query",
                    "description": "Execute a read-only SQL query",
                    "input_schema": {"sql": "string", "params": "any[]?"},
                    "destructive": False,
                },
                {
                    "name": "get_tables",
                    "description": "List available tables",
                    "input_schema": {},
                    "destructive": False,
                },
            ],
            "calculator": [
                {
                    "name": "math",
                    "description": "Evaluate a mathematical expression (AST-safe)",
                    "input_schema": {"expression": "string"},
                    "destructive": False,
                },
                {
                    "name": "date_calc",
                    "description": "Evaluate date arithmetic expressions",
                    "input_schema": {"expression": "string"},
                    "destructive": False,
                },
                {
                    "name": "threshold_check",
                    "description": "Compare a value against a threshold",
                    "input_schema": {"value": "float", "operator": "string", "threshold": "float"},
                    "destructive": False,
                },
            ],
        }

        tools: list[dict[str, Any]] = tool_definitions.get(server_name, [])
        tool_names: list[str] = []

        for tool_def in tools:
            tool_name: str = tool_def["name"]
            full_name: str = f"{server_name}/{tool_name}"
            info: ToolInfo = ToolInfo(
                name=tool_name,
                description=tool_def["description"],
                input_schema=tool_def.get("input_schema", {}),
                output_schema=tool_def.get("output_schema"),
                server=server_name,
                destructive=tool_def.get("destructive", False),
            )
            self._tools[full_name] = info
            self._tools[tool_name] = info  # Also register without prefix
            tool_names.append(tool_name)

        self._server_tools[server_name] = tool_names
        self._manager.cache_tools(server_name, tools)
        return len(tools)

    def get_tool(self, tool_name: str) -> ToolInfo | None:
        """Look up a tool by name.

        Supports both bare names ('describe_pods') and
        server-prefixed names ('aws-ecs/describe_pods').
        """
        return self._tools.get(tool_name)

    def has_tool(self, tool_name: str) -> bool:
        """Check if a tool is registered."""
        return tool_name in self._tools

    def list_tools(self) -> list[ToolInfo]:
        """List all registered tools (deduplicated)."""
        seen: set[str] = set()
        result: list[ToolInfo] = []
        for key, info in self._tools.items():
            if "/" in key:  # Only include fully-qualified names
                if info.name not in seen:
                    seen.add(info.name)
                    result.append(info)
        return result

    def list_server_tools(self, server_name: str) -> list[ToolInfo]:
        """List tools from a specific server."""
        names: list[str] = self._server_tools.get(server_name, [])
        return [self._tools[n] for n in names if n in self._tools]

    def get_available_tools_for_planning(self) -> list[dict[str, Any]]:
        """Get tool schemas in the format expected by the LLM planner."""
        schemas: list[dict[str, Any]] = []
        for key, info in self._tools.items():
            if "/" in key:  # Only fully-qualified
                schemas.append({
                    "name": key,
                    "description": info.description,
                    "input_schema": info.input_schema,
                    "destructive": info.destructive,
                })
        return schemas

    def get_server_for_tool(self, tool_name: str) -> str | None:
        """Get the server that provides a given tool."""
        info: ToolInfo | None = self._tools.get(tool_name)
        if info:
            return info.server
        # Try with server prefix
        for key, info in self._tools.items():
            if key.endswith(f"/{tool_name}"):
                return info.server
        return None

    async def refresh(self) -> int:
        """Force re-discovery of all tools.

        Returns:
            Total number of tools discovered.
        """
        logger.info("Refreshing tool registry...")
        return await self.discover_all()


# ---------------------------------------------------------------------------
# ModeRouter -- resolves execution mode and routes to mock or live
# ---------------------------------------------------------------------------


class ModeRouter:
    """Resolves execution mode per MCP server and routes tool calls.

    Priority: per-call override > server config > global default.
    Routes to MockFactory in MOCK mode, real transport in LIVE mode.
    """

    def __init__(
        self,
        client_manager: MCPClientManager,
        mock_factory: MockFactory | None = None,
    ) -> None:
        self._manager: MCPClientManager = client_manager
        self._mock: MockFactory = mock_factory or MockFactory()
        self._config = get_config()

    async def route_tool_call(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        mode_override: Literal["mock", "live", "local"] | None = None,
        command_text: str = "",
        step_index: int = 0,
    ) -> Any:
        """Route a tool call to the appropriate handler based on resolved mode.

        Args:
            server_name: MCP server name.
            tool_name: Tool to call.
            arguments: Tool arguments.
            mode_override: Per-call mode override (highest priority).
            command_text: Original command for seed derivation.
            step_index: Step index for deterministic mock seeding.

        Returns:
            Tool call result.

        Raises:
            CircuitBreakerOpenError: If the circuit breaker is open.
            MCPToolNotFoundError: If the tool is not available.
        """
        resolved_mode: Literal["mock", "live", "local"] = self.resolve_mode(
            server_name, mode_override
        )

        logger.info(
            "ModeRouter: %s/%s -> mode=%s (override=%s)",
            server_name,
            tool_name,
            resolved_mode,
            mode_override,
        )

        if resolved_mode in ("mock", "local"):
            return await self._mock.call_tool(
                server_name=server_name,
                tool_name=tool_name,
                arguments=arguments,
                command_text=command_text,
                step_index=step_index,
            )
        else:
            # LIVE mode: route to real MCP transport
            if not self._manager.is_connected(server_name):
                logger.warning(
                    "Server %s not connected in LIVE mode, falling back to mock",
                    server_name,
                )
                return await self._mock.call_tool(
                    server_name=server_name,
                    tool_name=tool_name,
                    arguments=arguments,
                    command_text=command_text,
                    step_index=step_index,
                )
            return await self._manager.call_tool(server_name, tool_name, arguments)

    def resolve_mode(
        self,
        server_name: str,
        mode_override: Literal["mock", "live", "local"] | None = None,
    ) -> Literal["mock", "live", "local"]:
        """Resolve execution mode for a server.

        Priority: per-call override > server config > global default.

        Args:
            server_name: The MCP server name.
            mode_override: Optional per-call mode override.

        Returns:
            Resolved execution mode.
        """
        # Priority 1: per-call override
        if mode_override is not None:
            return mode_override

        # Priority 2: server config
        server_mode: Literal["mock", "live", "local"] = self._config.get_server_mode(server_name)
        if server_mode != "mock":
            return server_mode

        # Priority 3: global default
        global_mode: str = self._config.app.execution_mode
        if global_mode == "mixed":
            return "mock"
        elif global_mode == "live":
            return "live"
        return "mock"

    def set_mock_factory(self, mock_factory: MockFactory) -> None:
        """Replace the mock factory (useful for testing)."""
        self._mock = mock_factory


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


async def create_mcp_hub(
    server_configs: dict[str, dict[str, Any]] | None = None,
) -> tuple[MCPClientManager, ToolRegistry, ModeRouter]:
    """Create and initialize the full MCP hub.

    Args:
        server_configs: Optional server configurations. Uses config defaults if not provided.

    Returns:
        Tuple of (client_manager, tool_registry, mode_router).
    """
    config = get_config()
    configs: dict[str, dict[str, Any]] = server_configs or {}

    if not configs:
        # Build from config
        for name, mcp_config in config.mcp_servers.items():
            configs[name] = {
                "transport": mcp_config.transport,
                "command": mcp_config.command,
                "url": mcp_config.url,
                "mode": mcp_config.mode,
                "timeout": mcp_config.timeout,
            }

    manager: MCPClientManager = MCPClientManager(configs)
    await manager.connect_all()

    registry: ToolRegistry = ToolRegistry(manager)
    await registry.discover_all()

    router: ModeRouter = ModeRouter(manager)

    logger.info(
        "MCP Hub initialized: %d/%d servers connected, %d tools registered",
        len(manager.connected_servers),
        manager.server_count,
        registry.tool_count,
    )
    return manager, registry, router
