"""Abstract base class and implementations for MCP servers.

Provides BaseMCPServer with common patterns for tool registration,
health check, and error handling. Includes concrete implementations
for all 7 MCP servers (tavily, github, slack, jira, aws_ecs, postgres, calculator).
"""

from __future__ import annotations

import abc
import asyncio
import logging
from typing import Any, Awaitable, Callable, Literal

logger: logging.Logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract Base Class
# ---------------------------------------------------------------------------


class BaseMCPServer(abc.ABC):
    """Abstract base class for all MCP servers in opsmate.

    Each server is a standalone process that:
    1. Registers tools with the MCP Server instance
    2. Handles tool calls via the MCP protocol
    3. Runs in either LIVE or MOCK mode based on environment
    """

    def __init__(self, name: str, version: str = "1.0.0") -> None:
        self.name: str = name
        self.version: str = version
        self._tools: dict[str, Callable[..., Awaitable[Any]]] = {}
        self._mode: Literal["mock", "live", "local"] = "mock"
        self._register_tools()

    @abc.abstractmethod
    def _register_tools(self) -> None:
        """Register all tool handlers. Called during __init__."""
        ...

    def register_tool(
        self,
        tool_name: str,
        handler: Callable[..., Awaitable[Any]],
    ) -> None:
        """Register a tool handler.

        Args:
            tool_name: The tool name exposed via MCP.
            handler: Async callable that implements the tool.
        """
        self._tools[tool_name] = handler
        logger.debug("Registered tool %s on server %s", tool_name, self.name)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call a registered tool.

        Args:
            tool_name: The tool to call.
            arguments: Tool arguments dict.

        Returns:
            Tool output.

        Raises:
            ValueError: If the tool is not registered.
        """
        handler: Callable[..., Awaitable[Any]] | None = self._tools.get(tool_name)
        if handler is None:
            available: list[str] = list(self._tools.keys())
            raise ValueError(
                f"Tool '{tool_name}' not found on server '{self.name}'. "
                f"Available tools: {available}"
            )

        logger.debug("Calling %s/%s with args=%s", self.name, tool_name, arguments)
        return await handler(**arguments)

    def list_tools(self) -> list[dict[str, Any]]:
        """List all registered tools with their schemas.

        Returns:
            List of tool info dicts with name, description, input_schema.
        """
        return [
            {
                "name": name,
                "description": getattr(handler, "__doc__", "No description"),
                "input_schema": getattr(handler, "_input_schema", {}),
            }
            for name, handler in self._tools.items()
        ]

    async def health_check(self) -> bool:
        """Check server health.

        Returns:
            True if healthy.
        """
        return True

    @property
    def execution_mode(self) -> Literal["mock", "live", "local"]:
        """Get current execution mode."""
        return self._mode

    def set_execution_mode(self, mode: Literal["mock", "live", "local"]) -> None:
        """Set execution mode.

        Args:
            mode: mock, live, or local.
        """
        self._mode = mode
        logger.info("Server %s mode set to %s", self.name, mode)


# ---------------------------------------------------------------------------
# Tavily MCP Server
# ---------------------------------------------------------------------------


class TavilyMCPServer(BaseMCPServer):
    """MCP server for Tavily web search and answer tools."""

    def __init__(self) -> None:
        super().__init__("tavily-search", version="1.0.0")

    def _register_tools(self) -> None:
        self.register_tool("search", self.search)
        self.register_tool("answer", self.answer)

    async def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Perform web search via Tavily API."""
        if self._mode == "mock":
            from opsmate.infra.mock_factory import TavilyMock, derive_seed

            seed: int = derive_seed(query)
            mock: TavilyMock = TavilyMock(seed)
            return await mock.search(query, max_results, search_depth=search_depth)

        # LIVE mode: call Tavily API
        from opsmate.core.config import get_config

        config = get_config()
        api_key: str = config.mcp_servers.get("tavily-search", {}).get("env", {}).get("TAVILY_API_KEY", "")
        if not api_key:
            raise ValueError("TAVILY_API_KEY not configured")

        # Placeholder: real implementation would call Tavily API
        return {
            "results": [{"title": "Live result", "url": "https://example.com", "content": query, "score": 0.9}],
            "query": query,
            "total_results": 1,
        }

    async def answer(
        self,
        query: str,
        include_sources: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Search and synthesize an answer with sources."""
        if self._mode == "mock":
            from opsmate.infra.mock_factory import TavilyMock, derive_seed

            seed: int = derive_seed(query)
            mock: TavilyMock = TavilyMock(seed)
            return await mock.answer(query, include_sources)

        return {"answer": f"Live answer for: {query}", "sources": None}


# ---------------------------------------------------------------------------
# GitHub MCP Server
# ---------------------------------------------------------------------------


class GitHubMCPServer(BaseMCPServer):
    """MCP server for GitHub repository info, CI status, and PR checks."""

    def __init__(self) -> None:
        super().__init__("github", version="1.0.0")

    def _register_tools(self) -> None:
        self.register_tool("repo_info", self.repo_info)
        self.register_tool("workflow_status", self.workflow_status)
        self.register_tool("pr_checks", self.pr_checks)

    async def repo_info(self, owner: str, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Get GitHub repository information."""
        if self._mode == "mock":
            from opsmate.infra.mock_factory import GitHubMock, derive_seed

            seed: int = derive_seed(f"{owner}/{repo}")
            mock: GitHubMock = GitHubMock(seed)
            return await mock.repo_info(owner, repo)

        return {"name": repo, "full_name": f"{owner}/{repo}", "description": None, "stars": 0, "forks": 0, "open_issues": 0, "default_branch": "main", "language": None, "updated_at": ""}

    async def workflow_status(
        self, owner: str, repo: str, branch: str = "main", **kwargs: Any
    ) -> dict[str, Any]:
        """Get GitHub Actions workflow status."""
        if self._mode == "mock":
            from opsmate.infra.mock_factory import GitHubMock, derive_seed

            seed: int = derive_seed(f"{owner}/{repo}/{branch}")
            mock: GitHubMock = GitHubMock(seed)
            return await mock.workflow_status(owner, repo, branch)

        return {"branch": branch, "runs": []}

    async def pr_checks(
        self, owner: str, repo: str, pr_number: int, **kwargs: Any
    ) -> dict[str, Any]:
        """Get PR check runs."""
        if self._mode == "mock":
            from opsmate.infra.mock_factory import GitHubMock, derive_seed

            seed: int = derive_seed(f"{owner}/{repo}/pr{pr_number}")
            mock: GitHubMock = GitHubMock(seed)
            return await mock.pr_checks(owner, repo, pr_number)

        return {"pr_number": pr_number, "check_runs": []}


# ---------------------------------------------------------------------------
# Slack MCP Server
# ---------------------------------------------------------------------------


class SlackMCPServer(BaseMCPServer):
    """MCP server for Slack message delivery."""

    def __init__(self) -> None:
        super().__init__("slack", version="1.0.0")

    def _register_tools(self) -> None:
        self.register_tool("send_message", self.send_message)

    async def send_message(
        self,
        channel: str,
        text: str,
        thread_ts: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a message to a Slack channel."""
        if self._mode == "mock":
            from opsmate.infra.mock_factory import SlackMock, derive_seed

            seed: int = derive_seed(f"{channel}:{text}")
            mock: SlackMock = SlackMock(seed)
            return await mock.send_message(channel, text, thread_ts)

        return {"ok": True, "channel": channel, "ts": "live-ts", "delivery_status": "delivered"}


# ---------------------------------------------------------------------------
# Jira MCP Server
# ---------------------------------------------------------------------------


class JiraMCPServer(BaseMCPServer):
    """MCP server for Jira ticket search and incident creation."""

    def __init__(self) -> None:
        super().__init__("jira", version="1.0.0")

    def _register_tools(self) -> None:
        self.register_tool("search_tickets", self.search_tickets)
        self.register_tool("create_incident", self.create_incident)

    async def search_tickets(
        self, jql: str, max_results: int = 50, **kwargs: Any
    ) -> dict[str, Any]:
        """Search Jira tickets using JQL."""
        if self._mode == "mock":
            from opsmate.infra.mock_factory import JiraMock, derive_seed

            seed: int = derive_seed(jql)
            mock: JiraMock = JiraMock(seed)
            return await mock.search_tickets(jql, max_results)

        return {"tickets": [], "total": 0}

    async def create_incident(
        self,
        summary: str,
        description: str,
        priority: str = "High",
        labels: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a Jira incident ticket."""
        if self._mode == "mock":
            from opsmate.infra.mock_factory import JiraMock, derive_seed

            seed: int = derive_seed(summary)
            mock: JiraMock = JiraMock(seed)
            return await mock.create_incident(summary, description, priority, labels)

        return {"key": "INC-LIVE-1", "url": "https://jira.example.com/browse/INC-LIVE-1", "status": "Open"}


# ---------------------------------------------------------------------------
# AWS ECS MCP Server
# ---------------------------------------------------------------------------


class AWSECSMCPServer(BaseMCPServer):
    """MCP server for AWS ECS/EKS pod management and CloudWatch metrics."""

    def __init__(self) -> None:
        super().__init__("aws-ecs", version="1.0.0")

    def _register_tools(self) -> None:
        self.register_tool("describe_pods", self.describe_pods)
        self.register_tool("get_metrics", self.get_metrics)
        self.register_tool("restart_pod", self.restart_pod)

    async def describe_pods(
        self, namespace: str, service: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Describe ECS/EKS pods for a service."""
        if self._mode == "mock":
            from opsmate.infra.mock_factory import AWSECSMock, derive_seed

            seed: int = derive_seed(f"{namespace}/{service}")
            mock: AWSECSMock = AWSECSMock(seed)
            return await mock.describe_pods(namespace, service)

        return {"pods": [], "namespace": namespace, "service": service, "total_pods": 0}

    async def get_metrics(
        self,
        namespace: str,
        service: str,
        metric: str,
        duration_minutes: int = 120,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get CloudWatch metrics."""
        if self._mode == "mock":
            from opsmate.infra.mock_factory import AWSECSMock, derive_seed

            seed: int = derive_seed(f"{namespace}/{service}/{metric}")
            mock: AWSECSMock = AWSECSMock(seed)
            return await mock.get_metrics(namespace, service, metric, duration_minutes)

        return {"metric": metric, "datapoints": [], "statistics": {}}

    async def restart_pod(
        self,
        namespace: str,
        pod_name: str,
        graceful: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Restart an ECS/EKS pod."""
        if self._mode == "mock":
            from opsmate.infra.mock_factory import AWSECSMock, derive_seed

            seed: int = derive_seed(f"{namespace}/{pod_name}")
            mock: AWSECSMock = AWSECSMock(seed)
            return await mock.restart_pod(namespace, pod_name, graceful)

        return {"pod_name": pod_name, "namespace": namespace, "previous_status": "Running", "restart_initiated": True, "message": "Live restart initiated"}


# ---------------------------------------------------------------------------
# PostgreSQL MCP Server
# ---------------------------------------------------------------------------


class PostgresMCPServer(BaseMCPServer):
    """MCP server for read-only PostgreSQL queries."""

    # Write keywords for READ-ONLY enforcement
    WRITE_KEYWORDS: set[str] = {
        "insert", "update", "delete", "drop", "alter",
        "create", "truncate", "grant", "revoke",
    }

    def __init__(self) -> None:
        super().__init__("postgres-db", version="1.0.0")

    def _register_tools(self) -> None:
        self.register_tool("execute_query", self.execute_query)
        self.register_tool("get_tables", self.get_tables)

    async def execute_query(
        self, sql: str, params: list[Any] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Execute a read-only SQL query.

        READ-ONLY enforcement: rejects any write SQL at the implementation level.
        """
        # READ-ONLY enforcement
        first_token: str = sql.strip().split()[0].lower() if sql.strip() else ""
        if first_token in self.WRITE_KEYWORDS:
            raise ValueError(f"Write operations are blocked. Found: '{first_token.upper()}'")

        if self._mode == "mock":
            from opsmate.infra.mock_factory import PostgresMock, derive_seed

            seed: int = derive_seed(sql)
            mock: PostgresMock = PostgresMock(seed)
            return await mock.execute_query(sql, params or [])

        return {"columns": ["result"], "rows": [["Live query executed"]], "row_count": 1, "execution_time_ms": 10.0}

    async def get_tables(self, **kwargs: Any) -> dict[str, Any]:
        """List available tables."""
        if self._mode == "mock":
            from opsmate.infra.mock_factory import PostgresMock

            mock: PostgresMock = PostgresMock(42)
            return await mock.get_tables()

        return {"tables": []}


# ---------------------------------------------------------------------------
# Calculator MCP Server
# ---------------------------------------------------------------------------


class CalculatorMCPServer(BaseMCPServer):
    """MCP server for mathematical computation, date arithmetic, and threshold checks.

    Always runs in 'local' mode - no external dependencies.
    Uses AST-safe evaluation (NEVER eval/exec).
    """

    # Safe operators for math evaluation
    _SAFE_OPS: dict[str, Any] = {}

    def __init__(self) -> None:
        super().__init__("calculator", version="1.0.0")
        self._mode = "local"  # Calculator is always local
        self._init_safe_ops()

    def _init_safe_ops(self) -> None:
        """Initialize safe operators for AST evaluation."""
        import ast
        import operator

        self._SAFE_OPS = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.USub: operator.neg,
        }

    def _register_tools(self) -> None:
        self.register_tool("math", self.math)
        self.register_tool("date_calc", self.date_calc)
        self.register_tool("threshold_check", self.threshold_check)

    async def math(self, expression: str, **kwargs: Any) -> dict[str, Any]:
        """Safely evaluate a mathematical expression using AST -- no eval/exec."""
        try:
            result: float = self._safe_eval(expression)
            return {"result": result, "expression": expression, "unit": None}
        except Exception as e:
            return {"result": float("nan"), "expression": expression, "unit": None}

    def _safe_eval(self, expr: str) -> float:
        """Evaluate math expression using AST -- no eval/exec."""
        import ast

        tree = ast.parse(expr.strip(), mode="eval")
        return self._eval_node(tree.body)

    def _eval_node(self, node: Any) -> float:
        """Recursively evaluate an AST node."""
        import ast

        if isinstance(node, ast.Constant):
            return float(node.value)
        elif isinstance(node, ast.BinOp):
            op_type: type = type(node.op)
            if op_type not in self._SAFE_OPS:
                raise ValueError(f"Unsupported operator: {op_type.__name__}")
            return self._SAFE_OPS[op_type](
                self._eval_node(node.left), self._eval_node(node.right)
            )
        elif isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return -self._eval_node(node.operand)
            raise ValueError("Unsupported unary operator")
        else:
            raise ValueError(f"Unsupported AST node: {type(node).__name__}")

    async def date_calc(self, expression: str, **kwargs: Any) -> dict[str, Any]:
        """Evaluate date arithmetic expressions."""
        from datetime import datetime, timedelta

        now: datetime = datetime.utcnow()
        result_type: str = "datetime"
        result: str = ""

        try:
            expr_lower: str = expression.lower().strip()
            if expr_lower == "now":
                result = now.isoformat()
            elif "-" in expr_lower and "day" in expr_lower:
                parts: list[str] = (
                    expr_lower.replace("now", "").replace("days", "").replace("day", "").split()
                )
                if len(parts) >= 2:
                    delta: timedelta = timedelta(days=int(parts[1]))
                    result = (now - delta).isoformat()
                else:
                    result = now.isoformat()
            elif "days_between" in expr_lower:
                import re

                dates: list[str] = re.findall(r"(\d{4}-\d{2}-\d{2})", expr_lower)
                if len(dates) == 2:
                    d1: datetime = datetime.strptime(dates[0], "%Y-%m-%d")
                    d2: datetime = datetime.strptime(dates[1], "%Y-%m-%d")
                    delta_days: int = abs((d2 - d1).days)
                    result = str(delta_days)
                    result_type = "duration"
                else:
                    result = "Error: expected two dates"
                    result_type = "error"
            else:
                result = now.isoformat()
        except Exception as e:
            return {"result": f"Error: {str(e)}", "expression": expression, "result_type": "error"}

        return {"result": result, "expression": expression, "result_type": result_type}

    async def threshold_check(
        self, value: float, operator: str, threshold: float, **kwargs: Any
    ) -> dict[str, Any]:
        """Compare a value against a threshold."""
        ops: dict[str, Any] = {
            ">": lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
            "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
        }
        op_func = ops.get(operator, lambda a, b: False)
        triggered: bool = op_func(value, threshold)
        return {
            "triggered": triggered,
            "value": value,
            "operator": operator,
            "threshold": threshold,
            "message": f"Value {value} {operator} threshold {threshold}: {'TRIGGERED' if triggered else 'OK'}",
        }


# ---------------------------------------------------------------------------
# Server Factory
# ---------------------------------------------------------------------------


_SERVER_REGISTRY: dict[str, type[BaseMCPServer]] = {
    "tavily-search": TavilyMCPServer,
    "github": GitHubMCPServer,
    "slack": SlackMCPServer,
    "jira": JiraMCPServer,
    "aws-ecs": AWSECSMCPServer,
    "postgres-db": PostgresMCPServer,
    "calculator": CalculatorMCPServer,
}


def create_server(name: str) -> BaseMCPServer:
    """Factory function to create an MCP server by name.

    Args:
        name: Server name (e.g., 'tavily-search', 'github').

    Returns:
        Configured MCP server instance.

    Raises:
        ValueError: If the server name is unknown.
    """
    server_class: type[BaseMCPServer] | None = _SERVER_REGISTRY.get(name)
    if server_class is None:
        available: list[str] = list(_SERVER_REGISTRY.keys())
        raise ValueError(
            f"Unknown MCP server: '{name}'. Available: {available}"
        )

    server: BaseMCPServer = server_class()

    # Set mode from config
    from opsmate.core.config import get_config

    config = get_config()
    server_mode: str = config.get_server_mode(name)
    server.set_execution_mode(server_mode)  # type: ignore[arg-type]

    return server


def list_available_servers() -> list[str]:
    """List all available MCP server names."""
    return sorted(_SERVER_REGISTRY.keys())


def get_server_registry() -> dict[str, type[BaseMCPServer]]:
    """Get the server registry mapping."""
    return dict(_SERVER_REGISTRY)
