"""Deterministic mock implementations for all 7 MCP servers.

The MockFactory provides realistic synthetic data using seeded Faker instances.
Same input always produces identical output. Supports latency injection and
configurable error simulation for testing.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import operator
import random
import re
import statistics
from datetime import datetime, timedelta
from typing import Any

from opsmate.core.exceptions import ExecutionError
from opsmate.core.models import (
    AWSDescribePodsOutput,
    AWSGetMetricsOutput,
    AWSRestartPodOutput,
    CalculatorDateOutput,
    CalculatorMathOutput,
    CalculatorThresholdOutput,
    GitHubPRChecksOutput,
    GitHubRepoInfoOutput,
    GitHubWorkflowStatusOutput,
    JiraSearchTicketsOutput,
    PostgresExecuteQueryOutput,
    SlackSendMessageOutput,
    TavilyAnswerOutput,
    TavilySearchOutput,
    derive_seed,
)

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AST-safe math evaluator (NEVER uses eval/exec)
# ---------------------------------------------------------------------------

_SAFE_OPS: dict[type, Any] = {
    "Add": operator.add,
    "Sub": operator.sub,
    "Mult": operator.mul,
    "Div": operator.truediv,
    "Pow": operator.pow,
    "USub": operator.neg,
}


def _safe_math_eval(expression: str) -> float:
    """Safely evaluate a mathematical expression using AST -- no eval/exec.

    Args:
        expression: Math expression string like '(100 - 80) / 80 * 100'.

    Returns:
        Computed float result.

    Raises:
        ValueError: If the expression contains unsupported operations.
    """
    import ast

    tree = ast.parse(expression.strip(), mode="eval")

    def _eval_node(node: ast.AST) -> float:
        if isinstance(node, ast.Constant):
            return float(node.value)
        elif isinstance(node, ast.BinOp):
            op_name: str = type(node.op).__name__
            if op_name not in _SAFE_OPS:
                raise ValueError(f"Unsupported operator: {op_name}")
            return _SAFE_OPS[op_name](_eval_node(node.left), _eval_node(node.right))
        elif isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return -_eval_node(node.operand)
            raise ValueError("Unsupported unary operator")
        else:
            raise ValueError(f"Unsupported AST node: {type(node).__name__}")

    return _eval_node(tree.body)


# ---------------------------------------------------------------------------
# Individual mock server implementations
# ---------------------------------------------------------------------------


class TavilyMock:
    """Deterministic mock for Tavily search tools."""

    def __init__(self, seed: int) -> None:
        from faker import Faker

        self.faker: Any = Faker()
        self.faker.seed_instance(seed)

    async def search(self, query: str, max_results: int = 5, **kwargs: Any) -> dict[str, Any]:
        await self._inject_latency(50, 150)
        count: int = min(max_results, 10)
        results: list[dict[str, Any]] = []
        for _ in range(count):
            domain: str = self.faker.domain_name()
            results.append({
                "title": self.faker.sentence(nb_words=8),
                "url": f"https://{domain}/{self.faker.uri_path()}",
                "content": self.faker.paragraph(nb_sentences=3),
                "score": round(self.faker.random.uniform(0.5, 0.99), 2),
            })
        return {"results": results, "query": query, "total_results": len(results)}

    async def answer(self, query: str, include_sources: bool = True, **kwargs: Any) -> dict[str, Any]:
        await self._inject_latency(100, 200)
        answer_text: str = self.faker.paragraph(nb_sentences=5)
        sources = None
        if include_sources:
            sources = (await self.search(query, max_results=3))["results"]
        return {"answer": answer_text, "sources": sources}

    async def _inject_latency(self, min_ms: int, max_ms: int) -> None:
        await asyncio.sleep(self.faker.random.randint(min_ms, max_ms) / 1000)


class GitHubMock:
    """Deterministic mock for GitHub tools."""

    def __init__(self, seed: int) -> None:
        from faker import Faker

        self.faker: Any = Faker()
        self.faker.seed_instance(seed)

    async def repo_info(self, owner: str, repo: str, **kwargs: Any) -> dict[str, Any]:
        await self._inject_latency(50, 120)
        return {
            "name": repo,
            "full_name": f"{owner}/{repo}",
            "description": self.faker.sentence(nb_words=10),
            "stars": self.faker.random_int(min=10, max=50000),
            "forks": self.faker.random_int(min=0, max=5000),
            "open_issues": self.faker.random_int(min=0, max=200),
            "default_branch": self.faker.random_element(["main", "master"]),
            "language": self.faker.random_element(["Python", "Go", "TypeScript", "Java", "Rust"]),
            "updated_at": self.faker.iso8601(),
        }

    async def workflow_status(self, owner: str, repo: str, branch: str = "main", **kwargs: Any) -> dict[str, Any]:
        await self._inject_latency(80, 180)
        statuses: list[str] = ["queued", "in_progress", "completed"]
        conclusions: list[str | None] = ["success", "failure", "cancelled", None]
        runs: list[dict[str, Any]] = []
        for _ in range(self.faker.random_int(min=1, max=5)):
            run_id: int = self.faker.random_int(min=1000000, max=9999999)
            runs.append({
                "id": run_id,
                "name": self.faker.random_element(["CI", "Build", "Test", "Deploy", "Lint"]),
                "status": self.faker.random_element(statuses),
                "conclusion": self.faker.random_element(conclusions),
                "created_at": self.faker.iso8601(),
                "html_url": f"https://github.com/{owner}/{repo}/actions/runs/{run_id}",
            })
        return {"branch": branch, "runs": runs}

    async def pr_checks(self, owner: str, repo: str, pr_number: int, **kwargs: Any) -> dict[str, Any]:
        await self._inject_latency(60, 150)
        check_names: list[str] = ["unit-tests", "integration-tests", "lint", "security-scan", "build"]
        check_runs: list[dict[str, Any]] = []
        for name in check_names[: self.faker.random_int(min=3, max=5)]:
            check_runs.append({
                "name": name,
                "status": "completed",
                "conclusion": self.faker.random_element(["success", "failure", "neutral"]),
            })
        return {"pr_number": pr_number, "check_runs": check_runs}

    async def _inject_latency(self, min_ms: int, max_ms: int) -> None:
        await asyncio.sleep(self.faker.random.randint(min_ms, max_ms) / 1000)


class SlackMock:
    """Deterministic mock for Slack tools."""

    def __init__(self, seed: int) -> None:
        from faker import Faker

        self.faker: Any = Faker()
        self.faker.seed_instance(seed)
        self._sent_messages: list[dict[str, Any]] = []

    async def send_message(self, channel: str, text: str, thread_ts: str | None = None, **kwargs: Any) -> dict[str, Any]:
        await self._inject_latency(50, 100)
        message_id: str = (
            f"{self.faker.random_int(min=1000000000, max=9999999999)}."
            f"{self.faker.random_int(min=100000, max=999999)}"
        )
        result: dict[str, Any] = {
            "ok": True,
            "channel": channel,
            "ts": message_id,
            "delivery_status": "delivered",
        }
        self._sent_messages.append({"channel": channel, "text": text, "ts": message_id})
        return result

    def get_sent_messages(self) -> list[dict[str, Any]]:
        return list(self._sent_messages)

    async def _inject_latency(self, min_ms: int, max_ms: int) -> None:
        await asyncio.sleep(self.faker.random.randint(min_ms, max_ms) / 1000)


class JiraMock:
    """Deterministic mock for Jira tools."""

    PRIORITY_MAP: dict[str, int] = {
        "Highest": 1, "High": 2, "Medium": 3, "Low": 4, "Lowest": 5,
    }

    def __init__(self, seed: int) -> None:
        from faker import Faker

        self.faker: Any = Faker()
        self.faker.seed_instance(seed)
        self._incident_counter: int = seed % 1000

    async def search_tickets(self, jql: str, max_results: int = 50, **kwargs: Any) -> dict[str, Any]:
        await self._inject_latency(80, 200)
        priorities: list[str] = ["Highest", "High", "Medium", "Low"]
        statuses: list[str] = ["Open", "In Progress", "Resolved", "Closed"]
        count: int = min(max_results, self.faker.random_int(min=0, max=20))
        tickets: list[dict[str, Any]] = []
        for _ in range(count):
            project: str = self.faker.random_element(["OPS", "INFRA", "SRE", "DEV", "PLAT"])
            ticket_num: int = self.faker.random_int(min=1, max=9999)
            tickets.append({
                "key": f"{project}-{ticket_num}",
                "summary": self.faker.sentence(nb_words=8),
                "status": self.faker.random_element(statuses),
                "priority": self.faker.random_element(priorities),
                "assignee": self.faker.email() if self.faker.boolean(chance_of_getting_true=70) else None,
                "created": self.faker.iso8601(),
                "updated": self.faker.iso8601(),
            })
        return {"tickets": tickets, "total": count}

    async def create_incident(self, summary: str, description: str, priority: str = "High", labels: list[str] | None = None, **kwargs: Any) -> dict[str, Any]:
        await self._inject_latency(60, 150)
        self._incident_counter += 1
        return {
            "key": f"INC-{self._incident_counter}",
            "url": f"https://jira.example.com/browse/INC-{self._incident_counter}",
            "status": "Open",
        }

    async def _inject_latency(self, min_ms: int, max_ms: int) -> None:
        await asyncio.sleep(self.faker.random.randint(min_ms, max_ms) / 1000)


class AWSECSMock:
    """Deterministic mock for AWS ECS tools with realistic data."""

    def __init__(self, seed: int) -> None:
        from faker import Faker

        self.faker: Any = Faker()
        self.faker.seed_instance(seed)
        self._restarted_pods: set[str] = set()

    async def describe_pods(self, namespace: str, service: str, **kwargs: Any) -> dict[str, Any]:
        await self._inject_latency(80, 180)
        pod_count: int = self.faker.random_int(min=2, max=10)
        statuses: list[str] = ["Running", "Running", "Running", "Pending", "CrashLoopBackOff"]
        pods: list[dict[str, Any]] = []
        for i in range(pod_count):
            pod_name: str = f"{service}-{self.faker.hexify(text='^^^^^^^', upper=False)}-{i}"
            pods.append({
                "name": pod_name,
                "namespace": namespace,
                "status": self.faker.random_element(statuses),
                "restarts": self.faker.random_int(min=0, max=5),
                "cpu_percent": round(self.faker.random.uniform(5, 98), 1),
                "memory_percent": round(self.faker.random.uniform(10, 90), 1),
                "age": f"{self.faker.random_int(min=1, max=72)}h",
                "node": f"ip-10-0-{self.faker.random_int(min=1, max=255)}-{self.faker.random_int(min=1, max=99)}.ec2.internal",
            })
        return {"pods": pods, "namespace": namespace, "service": service, "total_pods": len(pods)}

    async def get_metrics(self, namespace: str, service: str, metric: str, duration_minutes: int = 120, **kwargs: Any) -> dict[str, Any]:
        await self._inject_latency(100, 250)
        base_values: dict[str, float] = {
            "cpu": 45.0, "memory": 60.0, "requests": 100.0, "errors": 2.0, "latency": 50.0,
        }
        base_value: float = base_values.get(metric, 50.0)
        units: dict[str, str] = {
            "cpu": "Percent", "memory": "Percent", "requests": "Count",
            "errors": "Count", "latency": "Milliseconds",
        }
        datapoints: list[dict[str, Any]] = []
        num_points: int = max(duration_minutes // 5, 1)
        for i in range(num_points):
            value: float = base_value + random.gauss(0, base_value * 0.15)
            hour: int = i // 12
            minute: int = (i % 12) * 5
            datapoints.append({
                "timestamp": f"2025-01-01T{hour:02d}:{minute:02d}:00Z",
                "value": round(max(0, value), 2),
                "unit": units.get(metric, "Count"),
            })
        values: list[float] = [d["value"] for d in datapoints]
        return {
            "metric": metric,
            "datapoints": datapoints,
            "statistics": {
                "avg": round(statistics.mean(values), 2),
                "min": round(min(values), 2),
                "max": round(max(values), 2),
                "p99": round(sorted(values)[int(len(values) * 0.99) - 1] if values else 0, 2),
            },
        }

    async def restart_pod(self, namespace: str, pod_name: str, graceful: bool = True, **kwargs: Any) -> dict[str, Any]:
        await self._inject_latency(200, 500)
        self._restarted_pods.add(pod_name)
        return {
            "pod_name": pod_name,
            "namespace": namespace,
            "previous_status": "Running",
            "restart_initiated": True,
            "message": f"Pod {pod_name} restart initiated (graceful={graceful})",
        }

    async def _inject_latency(self, min_ms: int, max_ms: int) -> None:
        await asyncio.sleep(self.faker.random.randint(min_ms, max_ms) / 1000)


class PostgresMock:
    """Deterministic mock for read-only PostgreSQL queries."""

    MOCK_TABLES: dict[str, list[dict[str, str]]] = {
        "lambda_invocations": [
            {"column_name": "function_name", "data_type": "varchar"},
            {"column_name": "invocation_date", "data_type": "date"},
            {"column_name": "duration_ms", "data_type": "float"},
            {"column_name": "memory_mb", "data_type": "int"},
            {"column_name": "cold_start", "data_type": "boolean"},
        ],
        "ecs_services": [
            {"column_name": "service_name", "data_type": "varchar"},
            {"column_name": "cluster", "data_type": "varchar"},
            {"column_name": "running_count", "data_type": "int"},
            {"column_name": "desired_count", "data_type": "int"},
            {"column_name": "cpu_utilization", "data_type": "float"},
        ],
        "deployments": [
            {"column_name": "service", "data_type": "varchar"},
            {"column_name": "version", "data_type": "varchar"},
            {"column_name": "deployed_at", "data_type": "timestamp"},
            {"column_name": "status", "data_type": "varchar"},
        ],
    }

    def __init__(self, seed: int) -> None:
        from faker import Faker

        self.faker: Any = Faker()
        self.faker.seed_instance(seed)

    async def execute_query(self, sql: str, params: list[Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        await self._inject_latency(30, 120)
        lower_sql: str = sql.lower()
        # WRITE-ONLY enforcement at mock level too
        write_keywords: set[str] = {
            "insert", "update", "delete", "drop", "alter",
            "create", "truncate", "grant", "revoke",
        }
        first_token: str = lower_sql.strip().split()[0] if lower_sql.strip() else ""
        if first_token in write_keywords:
            raise ExecutionError(f"Write operations are blocked. Found: '{first_token.upper()}'")

        if "lambda_invocations" in lower_sql:
            return self._mock_lambda_results()
        elif "ecs_services" in lower_sql:
            return self._mock_ecs_results()
        elif "deployments" in lower_sql:
            return self._mock_deployment_results()
        else:
            return {"columns": ["result"], "rows": [["Mock query executed"]], "row_count": 1, "execution_time_ms": 15.2}

    async def get_tables(self, **kwargs: Any) -> dict[str, Any]:
        return {"tables": list(self.MOCK_TABLES.keys())}

    def _mock_lambda_results(self) -> dict[str, Any]:
        functions: list[str] = [
            "payment-processor", "notification-sender", "auth-validator",
            "report-generator", "data-transformer",
        ]
        rows: list[list[Any]] = []
        for fn in functions:
            for day in range(7):
                rows.append([
                    fn,
                    f"2025-05-{25 + day:02d}",
                    round(self.faker.random.uniform(50, 800), 1),
                    self.faker.random_element([128, 256, 512, 1024]),
                    self.faker.boolean(chance_of_getting_true=20),
                ])
        return {
            "columns": ["function_name", "invocation_date", "duration_ms", "memory_mb", "cold_start"],
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": round(self.faker.random.uniform(5, 50), 1),
        }

    def _mock_ecs_results(self) -> dict[str, Any]:
        services: list[str] = [
            "payment-service", "api-gateway", "user-service",
            "order-service", "inventory-service",
        ]
        rows: list[list[Any]] = []
        for s in services:
            rows.append([
                s, "prod-cluster",
                self.faker.random_int(2, 10),
                self.faker.random_int(2, 10),
                round(self.faker.random.uniform(20, 85), 1),
            ])
        return {
            "columns": ["service_name", "cluster", "running_count", "desired_count", "cpu_utilization"],
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": round(self.faker.random.uniform(5, 30), 1),
        }

    def _mock_deployment_results(self) -> dict[str, Any]:
        services: list[str] = ["payment-service", "api-gateway", "user-service"]
        rows: list[list[Any]] = []
        for s in services:
            for _ in range(3):
                rows.append([
                    s,
                    f"1.{self.faker.random_int(10, 99)}.{self.faker.random_int(0, 9)}",
                    f"2025-05-{self.faker.random_int(20, 30):02d}T{self.faker.random_int(0, 23):02d}:00:00Z",
                    self.faker.random_element(["success", "failed", "rolled_back"]),
                ])
        return {
            "columns": ["service", "version", "deployed_at", "status"],
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": round(self.faker.random.uniform(5, 20), 1),
        }

    async def _inject_latency(self, min_ms: int, max_ms: int) -> None:
        await asyncio.sleep(self.faker.random.randint(min_ms, max_ms) / 1000)


class CalculatorMock:
    """Local-only calculator implementation. Uses AST-safe evaluation."""

    def __init__(self, _seed: int) -> None:
        """Calculator doesn't need seeding but accepts for interface consistency."""
        pass

    async def math(self, expression: str, **kwargs: Any) -> dict[str, Any]:
        try:
            result: float = _safe_math_eval(expression)
            return {"result": result, "expression": expression, "unit": None}
        except Exception as e:
            return {"result": float("nan"), "expression": expression, "unit": None}

    async def date_calc(self, expression: str, **kwargs: Any) -> dict[str, Any]:
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

    async def threshold_check(self, value: float, operator: str, threshold: float, **kwargs: Any) -> dict[str, Any]:
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
# MockFactory -- unified interface
# ---------------------------------------------------------------------------


class MockFactory:
    """Unified mock factory for all MCP servers.

    Provides deterministic, seeded mock data generation with configurable
    latency injection and error simulation.
    """

    def __init__(
        self,
        latency_ms: tuple[int, int] = (50, 200),
        error_rate: float = 0.0,
    ) -> None:
        self.latency_ms = latency_ms
        self.error_rate = error_rate
        self._mocks: dict[str, Any] = {}
        self._call_count: int = 0

    def _get_mock(self, server_name: str, command_text: str = "", step_index: int = 0) -> Any:
        """Get or create a seeded mock instance for a server."""
        seed: int = derive_seed(command_text, step_index)
        cache_key: str = f"{server_name}:{seed}"
        if cache_key not in self._mocks:
            mock_class: type | None = _MOCK_REGISTRY.get(server_name)
            if mock_class is None:
                raise ExecutionError(f"No mock implementation for server: {server_name}")
            self._mocks[cache_key] = mock_class(seed)
        return self._mocks[cache_key]

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        command_text: str = "",
        step_index: int = 0,
    ) -> Any:
        """Call a mock tool implementation.

        Args:
            server_name: MCP server name (e.g., 'aws-ecs').
            tool_name: Tool name (e.g., 'describe_pods').
            arguments: Tool arguments dict.
            command_text: Original command for seed derivation.
            step_index: Step index for deterministic seeding.

        Returns:
            Tool output dict.

        Raises:
            ExecutionError: If error simulation triggers or tool not found.
        """
        self._call_count += 1

        # Error simulation
        if self.error_rate > 0 and random.random() < self.error_rate:
            raise ExecutionError(
                f"Simulated error in {server_name}/{tool_name}",
                details={"server": server_name, "tool": tool_name, "simulated": True},
            )

        mock: Any = self._get_mock(server_name, command_text, step_index)
        method = getattr(mock, tool_name, None)
        if method is None:
            raise ExecutionError(
                f"Mock tool '{tool_name}' not found on server '{server_name}'",
                details={"available": [m for m in dir(mock) if not m.startswith("_")]},
            )

        logger.debug("Mock call: %s/%s(args=%s)", server_name, tool_name, arguments)
        result: Any = await method(**arguments)
        return result

    async def tavily_search(
        self, query: str, max_results: int = 5, *, command_text: str = "", step_index: int = 0,
    ) -> TavilySearchOutput:
        """Mock tavily-search tool."""
        raw: dict[str, Any] = await self.call_tool(
            "tavily-search", "search",
            {"query": query, "max_results": max_results},
            command_text=command_text, step_index=step_index,
        )
        return TavilySearchOutput.model_validate(raw)

    async def tavily_answer(
        self, query: str, include_sources: bool = True, *, command_text: str = "", step_index: int = 0,
    ) -> TavilyAnswerOutput:
        """Mock tavily-answer tool."""
        raw: dict[str, Any] = await self.call_tool(
            "tavily-search", "answer",
            {"query": query, "include_sources": include_sources},
            command_text=command_text, step_index=step_index,
        )
        return TavilyAnswerOutput.model_validate(raw)

    async def github_repo_info(
        self, owner: str, repo: str, *, command_text: str = "", step_index: int = 0,
    ) -> GitHubRepoInfoOutput:
        """Mock github-repo_info tool."""
        raw: dict[str, Any] = await self.call_tool(
            "github", "repo_info",
            {"owner": owner, "repo": repo},
            command_text=command_text, step_index=step_index,
        )
        return GitHubRepoInfoOutput.model_validate(raw)

    async def github_workflow_status(
        self, owner: str, repo: str, branch: str = "main", *, command_text: str = "", step_index: int = 0,
    ) -> GitHubWorkflowStatusOutput:
        """Mock github-workflow_status tool."""
        raw: dict[str, Any] = await self.call_tool(
            "github", "workflow_status",
            {"owner": owner, "repo": repo, "branch": branch},
            command_text=command_text, step_index=step_index,
        )
        return GitHubWorkflowStatusOutput.model_validate(raw)

    async def github_pr_checks(
        self, owner: str, repo: str, pr_number: int, *, command_text: str = "", step_index: int = 0,
    ) -> GitHubPRChecksOutput:
        """Mock github-pr_checks tool."""
        raw: dict[str, Any] = await self.call_tool(
            "github", "pr_checks",
            {"owner": owner, "repo": repo, "pr_number": pr_number},
            command_text=command_text, step_index=step_index,
        )
        return GitHubPRChecksOutput.model_validate(raw)

    async def slack_send_message(
        self, channel: str, text: str, thread_ts: str | None = None, *, command_text: str = "", step_index: int = 0,
    ) -> SlackSendMessageOutput:
        """Mock slack-send_message tool."""
        raw: dict[str, Any] = await self.call_tool(
            "slack", "send_message",
            {"channel": channel, "text": text, "thread_ts": thread_ts},
            command_text=command_text, step_index=step_index,
        )
        return SlackSendMessageOutput.model_validate(raw)

    async def jira_search_tickets(
        self, jql: str, max_results: int = 50, *, command_text: str = "", step_index: int = 0,
    ) -> JiraSearchTicketsOutput:
        """Mock jira-search_tickets tool."""
        raw: dict[str, Any] = await self.call_tool(
            "jira", "search_tickets",
            {"jql": jql, "max_results": max_results},
            command_text=command_text, step_index=step_index,
        )
        return JiraSearchTicketsOutput.model_validate(raw)

    async def jira_create_incident(
        self, summary: str, description: str, priority: str = "High", labels: list[str] | None = None, *,
        command_text: str = "", step_index: int = 0,
    ) -> dict[str, Any]:
        """Mock jira-create_incident tool."""
        return await self.call_tool(
            "jira", "create_incident",
            {"summary": summary, "description": description, "priority": priority, "labels": labels or ["incident", "auto-generated"]},
            command_text=command_text, step_index=step_index,
        )

    async def aws_describe_pods(
        self, namespace: str, service: str, *, command_text: str = "", step_index: int = 0,
    ) -> AWSDescribePodsOutput:
        """Mock aws-describe_pods tool."""
        raw: dict[str, Any] = await self.call_tool(
            "aws-ecs", "describe_pods",
            {"namespace": namespace, "service": service},
            command_text=command_text, step_index=step_index,
        )
        return AWSDescribePodsOutput.model_validate(raw)

    async def aws_get_metrics(
        self, namespace: str, service: str, metric: str, duration_minutes: int = 120, *,
        command_text: str = "", step_index: int = 0,
    ) -> AWSGetMetricsOutput:
        """Mock aws-get_metrics tool."""
        raw: dict[str, Any] = await self.call_tool(
            "aws-ecs", "get_metrics",
            {"namespace": namespace, "service": service, "metric": metric, "duration_minutes": duration_minutes},
            command_text=command_text, step_index=step_index,
        )
        return AWSGetMetricsOutput.model_validate(raw)

    async def aws_restart_pod(
        self, namespace: str, pod_name: str, graceful: bool = True, *, command_text: str = "", step_index: int = 0,
    ) -> AWSRestartPodOutput:
        """Mock aws-restart_pod tool."""
        raw: dict[str, Any] = await self.call_tool(
            "aws-ecs", "restart_pod",
            {"namespace": namespace, "pod_name": pod_name, "graceful": graceful},
            command_text=command_text, step_index=step_index,
        )
        return AWSRestartPodOutput.model_validate(raw)

    async def postgres_execute_query(
        self, sql: str, params: list[Any] | None = None, *, command_text: str = "", step_index: int = 0,
    ) -> PostgresExecuteQueryOutput:
        """Mock postgres-execute_query tool. READ-ONLY enforcement."""
        # Reject write operations
        write_keywords: set[str] = {
            "insert", "update", "delete", "drop", "alter",
            "create", "truncate", "grant", "revoke",
        }
        first_token: str = sql.strip().split()[0].lower() if sql.strip() else ""
        if first_token in write_keywords:
            raise ExecutionError(f"Write operations are blocked. Found: '{first_token.upper()}'")

        raw: dict[str, Any] = await self.call_tool(
            "postgres-db", "execute_query",
            {"sql": sql, "params": params or []},
            command_text=command_text, step_index=step_index,
        )
        return PostgresExecuteQueryOutput.model_validate(raw)

    async def calculator_math(
        self, expression: str, *, command_text: str = "", step_index: int = 0,
    ) -> CalculatorMathOutput:
        """Mock calculator-math tool. AST-safe evaluation."""
        raw: dict[str, Any] = await self.call_tool(
            "calculator", "math",
            {"expression": expression},
            command_text=command_text, step_index=step_index,
        )
        return CalculatorMathOutput.model_validate(raw)

    async def calculator_date_calc(
        self, expression: str, *, command_text: str = "", step_index: int = 0,
    ) -> CalculatorDateOutput:
        """Mock calculator-date_calc tool."""
        raw: dict[str, Any] = await self.call_tool(
            "calculator", "date_calc",
            {"expression": expression},
            command_text=command_text, step_index=step_index,
        )
        return CalculatorDateOutput.model_validate(raw)

    async def calculator_threshold_check(
        self, value: float, operator: str, threshold: float, *, command_text: str = "", step_index: int = 0,
    ) -> CalculatorThresholdOutput:
        """Mock calculator-threshold_check tool."""
        raw: dict[str, Any] = await self.call_tool(
            "calculator", "threshold_check",
            {"value": value, "operator": operator, "threshold": threshold},
            command_text=command_text, step_index=step_index,
        )
        return CalculatorThresholdOutput.model_validate(raw)


# Registry of mock implementations by server name
_MOCK_REGISTRY: dict[str, type] = {
    "tavily-search": TavilyMock,
    "github": GitHubMock,
    "slack": SlackMock,
    "jira": JiraMock,
    "aws-ecs": AWSECSMock,
    "postgres-db": PostgresMock,
    "calculator": CalculatorMock,
}


def get_mock_registry() -> dict[str, type]:
    """Get the mock registry mapping server names to mock classes."""
    return dict(_MOCK_REGISTRY)
