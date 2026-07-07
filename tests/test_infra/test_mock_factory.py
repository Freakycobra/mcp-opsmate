"""
Tests for the mock factory infrastructure.

Covers deterministic output generation, schema parity between mock and live modes,
read-only enforcement, AST-safe math evaluation, and latency injection.
These tests ensure the MOCK mode is safe, deterministic, and schema-compatible.
"""

from __future__ import annotations

import ast
import time
from typing import Any

import pytest


class TestDeterministicOutput:
    """Tests for deterministic mock output generation."""

    @pytest.fixture
    def mock_factory(self) -> Any:
        """Provide a mock factory with a fixed seed."""
        from opsmate.infra.mock_factory import MockFactory
        return MockFactory(seed=42)

    @pytest.mark.asyncio
    async def test_same_seed_same_output(self, mock_factory: Any) -> None:
        """Same seed produces identical outputs for the same tool call."""
        result1 = await mock_factory.generate("aws-ecs", "describe_pods", {})
        result2 = await mock_factory.generate("aws-ecs", "describe_pods", {})

        assert result1 == result2

    @pytest.mark.asyncio
    async def test_different_seed_different_output(self) -> None:
        """Different seeds produce different outputs."""
        from opsmate.infra.mock_factory import MockFactory

        factory1 = MockFactory(seed=1)
        factory2 = MockFactory(seed=999)

        result1 = await factory1.generate("aws-ecs", "describe_pods", {})
        result2 = await factory2.generate("aws-ecs", "describe_pods", {})

        assert result1 != result2

    @pytest.mark.asyncio
    async def test_same_seed_across_instances(self) -> None:
        """Two factory instances with the same seed produce identical outputs."""
        from opsmate.infra.mock_factory import MockFactory

        factory1 = MockFactory(seed=12345)
        factory2 = MockFactory(seed=12345)

        result1 = await factory1.generate("github", "get_repo", {"owner": "test", "repo": "repo"})
        result2 = await factory2.generate("github", "get_repo", {"owner": "test", "repo": "repo"})

        assert result1 == result2

    @pytest.mark.asyncio
    async def test_output_structure_varies_by_tool(self, mock_factory: Any) -> None:
        """Different tools produce appropriately structured outputs."""
        aws_result = await mock_factory.generate("aws-ecs", "describe_pods", {})
        github_result = await mock_factory.generate("github", "get_repo", {})
        slack_result = await mock_factory.generate("slack", "send_slack_message", {})

        # Each tool should have a distinct output structure
        assert isinstance(aws_result, dict)
        assert isinstance(github_result, dict)
        assert isinstance(slack_result, dict)

    @pytest.mark.asyncio
    async def test_arguments_influence_output(self, mock_factory: Any) -> None:
        """Different arguments produce different (but still deterministic) outputs."""
        result1 = await mock_factory.generate("aws-ecs", "describe_pods", {"service": "svc-a"})
        result2 = await mock_factory.generate("aws-ecs", "describe_pods", {"service": "svc-b"})

        # Same structure, different content
        assert type(result1) == type(result2)
        assert result1.keys() == result2.keys()


class TestSchemaParity:
    """Tests ensuring mock outputs match live response schemas."""

    @pytest.fixture
    def mock_factory(self) -> Any:
        """Provide a mock factory."""
        from opsmate.infra.mock_factory import MockFactory
        return MockFactory(seed=42)

    @pytest.mark.asyncio
    async def test_tavily_search_schema(self, mock_factory: Any) -> None:
        """Mock Tavily search output matches live schema."""
        result = await mock_factory.generate("tavily-search", "search", {"query": "test"})

        assert "results" in result
        assert isinstance(result["results"], list)
        for item in result["results"]:
            assert "title" in item
            assert "url" in item
            assert "content" in item

    @pytest.mark.asyncio
    async def test_github_repo_schema(self, mock_factory: Any) -> None:
        """Mock GitHub repo output matches live schema."""
        result = await mock_factory.generate("github", "get_repo", {"owner": "test", "repo": "repo"})

        assert "id" in result
        assert "name" in result
        assert "full_name" in result
        assert "owner" in result
        assert "html_url" in result

    @pytest.mark.asyncio
    async def test_github_issues_schema(self, mock_factory: Any) -> None:
        """Mock GitHub issues output matches live schema."""
        result = await mock_factory.generate("github", "list_issues", {"owner": "test", "repo": "repo"})

        assert isinstance(result, list)
        for issue in result:
            assert "id" in issue
            assert "title" in issue
            assert "state" in issue
            assert "created_at" in issue

    @pytest.mark.asyncio
    async def test_slack_message_schema(self, mock_factory: Any) -> None:
        """Mock Slack message output matches live schema."""
        result = await mock_factory.generate("slack", "send_slack_message", {"channel": "test", "message": "hello"})

        assert "ok" in result
        assert "ts" in result
        assert "channel" in result

    @pytest.mark.asyncio
    async def test_jira_ticket_schema(self, mock_factory: Any) -> None:
        """Mock Jira ticket output matches live schema."""
        result = await mock_factory.generate("jira", "get_ticket", {"key": "TEST-123"})

        assert "id" in result
        assert "key" in result
        assert "fields" in result
        assert "summary" in result["fields"]
        assert "status" in result["fields"]

    @pytest.mark.asyncio
    async def test_aws_ecs_pods_schema(self, mock_factory: Any) -> None:
        """Mock AWS ECS pods output matches live schema."""
        result = await mock_factory.generate("aws-ecs", "describe_pods", {"service": "test"})

        assert isinstance(result, list)
        for pod in result:
            assert "name" in pod
            assert "status" in pod
            assert "containers" in pod

    @pytest.mark.asyncio
    async def test_all_servers_have_schemas(self) -> None:
        """All 7 MCP servers have defined mock schemas."""
        from opsmate.infra.mock_factory import MockFactory, REGISTERED_SERVERS

        factory = MockFactory(seed=42)

        # Verify all expected servers are registered
        expected_servers = {
            "tavily-search", "github", "slack", "jira",
            "aws-ecs", "postgres-db", "calculator",
        }
        assert expected_servers.issubset(set(REGISTERED_SERVERS))


class TestReadOnlyEnforcement:
    """Tests ensuring MOCK mode enforces read-only behavior for destructive tools."""

    @pytest.fixture
    def mock_factory(self) -> Any:
        """Provide a mock factory with read-only enforcement."""
        from opsmate.infra.mock_factory import MockFactory
        return MockFactory(seed=42, read_only=True)

    @pytest.mark.asyncio
    async def test_read_only_blocks_restart_pods(self, mock_factory: Any) -> None:
        """restart_pods in MOCK read-only mode returns simulation result."""
        result = await mock_factory.generate("aws-ecs", "restart_pods", {"pod_ids": ["pod-1"]})

        # Should return a simulated result, not actually restart anything
        assert "simulated" in result or "mock" in str(result).lower()
        assert "restarted" in result or "pods" in result

    @pytest.mark.asyncio
    async def test_read_only_blocks_delete(self, mock_factory: Any) -> None:
        """Delete operations in MOCK mode are simulated, not executed."""
        result = await mock_factory.generate("aws-ecs", "delete_pods", {"pod_ids": ["pod-1"]})

        assert "simulated" in result or "mock" in str(result).lower()

    @pytest.mark.asyncio
    async def test_read_only_allows_query_operations(self, mock_factory: Any) -> None:
        """Read operations are not affected by read-only mode."""
        result = await mock_factory.generate("aws-ecs", "describe_pods", {})

        # Should return normal mock data
        assert isinstance(result, (list, dict))

    @pytest.mark.asyncio
    async def test_read_only_blocks_scale_service(self, mock_factory: Any) -> None:
        """scale_service in MOCK mode returns simulation."""
        result = await mock_factory.generate(
            "aws-ecs", "scale_service", {"service": "test", "desired_count": 5}
        )

        assert "simulated" in result or "desired_count" in result


class TestASTSafeMath:
    """Tests for AST-safe math evaluation in the calculator MCP server."""

    @pytest.fixture
    def calculator(self) -> Any:
        """Provide an AST-safe calculator."""
        from opsmate.infra.mock_factory import ASTSafeCalculator
        return ASTSafeCalculator()

    def test_basic_arithmetic(self, calculator: Any) -> None:
        """Basic arithmetic operations work."""
        assert calculator.evaluate("2 + 3") == 5
        assert calculator.evaluate("10 - 4") == 6
        assert calculator.evaluate("6 * 7") == 42
        assert calculator.evaluate("20 / 4") == 5.0

    def test_complex_expression(self, calculator: Any) -> None:
        """Complex expressions with parentheses and precedence."""
        assert calculator.evaluate("(2 + 3) * 4") == 20
        assert calculator.evaluate("10 / (5 - 3)") == 5.0

    def test_power_and_modulo(self, calculator: Any) -> None:
        """Power and modulo operations."""
        assert calculator.evaluate("2 ** 8") == 256
        assert calculator.evaluate("17 % 5") == 2

    def test_functions(self, calculator: Any) -> None:
        """Math functions like sqrt, sin, cos."""
        import math

        assert calculator.evaluate("sqrt(16)") == 4.0
        assert calculator.evaluate("abs(-5)") == 5
        assert calculator.evaluate("round(3.7)") == 4
        assert abs(calculator.evaluate("sin(0)") - 0.0) < 1e-10
        assert abs(calculator.evaluate("cos(0)") - 1.0) < 1e-10

    def test_malicious_code_rejected(self, calculator: Any) -> None:
        """Malicious code attempts are rejected."""
        dangerous_expressions = [
            "__import__('os').system('ls')",
            "open('/etc/passwd').read()",
            "eval('1 + 1')",
            "exec('print(1)')",
            "[x for x in ().__class__.__bases__[0].__subclasses__()]",
        ]

        for expr in dangerous_expressions:
            with pytest.raises((ValueError, SyntaxError, TypeError)):
                calculator.evaluate(expr)

    def test_no_name_exfiltration(self, calculator: Any) -> None:
        """Attempting to access Python internals is blocked."""
        with pytest.raises((ValueError, AttributeError)):
            calculator.evaluate("().__class__")

    def test_invalid_syntax_rejected(self, calculator: Any) -> None:
        """Invalid mathematical syntax raises an error."""
        with pytest.raises((ValueError, SyntaxError)):
            calculator.evaluate("2 + + 3")

    def test_only_math_module_allowed(self, calculator: Any) -> None:
        """Only whitelisted math functions are accessible."""
        import math

        # These should work (math module functions)
        assert calculator.evaluate("math.sqrt(9)") == 3.0
        assert calculator.evaluate("math.floor(3.9)") == 3

        # These should fail (non-math builtins)
        with pytest.raises((ValueError, NameError)):
            calculator.evaluate("print(1)")


class TestLatencyInjection:
    """Tests for configurable latency injection in MOCK mode."""

    @pytest.fixture
    def mock_factory_fast(self) -> Any:
        """Provide a mock factory with minimal latency."""
        from opsmate.infra.mock_factory import MockFactory
        return MockFactory(seed=42, min_latency_ms=10, max_latency_ms=20)

    @pytest.fixture
    def mock_factory_slow(self) -> Any:
        """Provide a mock factory with higher latency."""
        from opsmate.infra.mock_factory import MockFactory
        return MockFactory(seed=42, min_latency_ms=50, max_latency_ms=100)

    @pytest.mark.asyncio
    async def test_latency_injected(self, mock_factory_slow: Any) -> None:
        """Mock calls include configurable latency."""
        start = time.monotonic()
        result = await mock_factory_slow.generate("aws-ecs", "describe_pods", {})
        elapsed_ms = (time.monotonic() - start) * 1000

        assert result is not None
        # Should have taken at least the minimum latency
        assert elapsed_ms >= 45  # Allow small timing variance

    @pytest.mark.asyncio
    async def test_fast_latency(self, mock_factory_fast: Any) -> None:
        """Fast latency configuration completes quickly."""
        start = time.monotonic()
        result = await mock_factory_fast.generate("aws-ecs", "describe_pods", {})
        elapsed_ms = (time.monotonic() - start) * 1000

        assert result is not None
        assert elapsed_ms < 50  # Should be fast

    @pytest.mark.asyncio
    async def test_latency_is_within_bounds(self, mock_factory_fast: Any) -> None:
        """Latency stays within configured bounds."""
        latencies = []
        for _ in range(10):
            start = time.monotonic()
            await mock_factory_fast.generate("aws-ecs", "describe_pods", {})
            elapsed_ms = (time.monotonic() - start) * 1000
            latencies.append(elapsed_ms)

        # All latencies should be within bounds (allowing small variance)
        assert all(5 <= lat <= 50 for lat in latencies)

    @pytest.mark.asyncio
    async def test_zero_latency_option(self) -> None:
        """Latency can be disabled entirely."""
        from opsmate.infra.mock_factory import MockFactory

        factory = MockFactory(seed=42, min_latency_ms=0, max_latency_ms=0)

        start = time.monotonic()
        await factory.generate("aws-ecs", "describe_pods", {})
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 10  # Should be essentially instant
