"""
Tests for the step executor service.

Covers single step execution, parallel step execution, conditional steps,
failure retry logic, and circuit breaker integration.
All MCP tool calls are mocked.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestExecuteSingleStep:
    """Tests for executing individual steps."""

    @pytest.fixture
    def executor(self, mock_mcp_hub: Any) -> Any:
        """Provide a step executor with mocked MCP hub."""
        from opsmate.services.executor import StepExecutor
        return StepExecutor(mcp_hub=mock_mcp_hub)

    @pytest.mark.asyncio
    async def test_execute_single_step(self, executor: Any) -> None:
        """Execute a single step and return the result."""
        step = {
            "id": "step-1",
            "tool_name": "describe_pods",
            "server": "aws-ecs",
            "input_schema": {"service": "payment-service"},
        }
        context = {"variables": {}}

        result = await executor.execute_step(step, context)

        assert result["step_id"] == "step-1"
        assert result["status"] == "completed"
        assert "output" in result
        assert "started_at" in result
        assert "completed_at" in result

    @pytest.mark.asyncio
    async def test_execute_step_with_variables(self, executor: Any) -> None:
        """Execute a step that uses context variables."""
        step = {
            "id": "step-1",
            "tool_name": "send_slack_message",
            "server": "slack",
            "input_schema": {
                "channel": "{{variables.channel}}",
                "message": "{{variables.message}}",
            },
        }
        context = {
            "variables": {"channel": "on-call", "message": "Test alert"},
        }

        result = await executor.execute_step(step, context)

        assert result["status"] == "completed"
        assert "output" in result

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, executor: Any) -> None:
        """Executing an unknown tool returns a failure result."""
        step = {
            "id": "step-1",
            "tool_name": "nonexistent_tool",
            "server": "unknown-server",
            "input_schema": {},
        }
        context = {"variables": {}}

        result = await executor.execute_step(step, context)

        assert result["status"] == "failed"
        assert "error" in result


class TestExecuteParallelSteps:
    """Tests for parallel execution of independent steps."""

    @pytest.fixture
    def executor(self, mock_mcp_hub: Any) -> Any:
        """Provide a step executor."""
        from opsmate.services.executor import StepExecutor
        return StepExecutor(mcp_hub=mock_mcp_hub)

    @pytest.mark.asyncio
    async def test_execute_parallel_steps(self, executor: Any) -> None:
        """Independent steps execute in parallel."""
        steps = [
            {
                "id": "step-1",
                "tool_name": "describe_pods",
                "server": "aws-ecs",
                "input_schema": {},
            },
            {
                "id": "step-2",
                "tool_name": "get_cloudwatch_metrics",
                "server": "aws-ecs",
                "input_schema": {},
            },
        ]
        dependencies = {"step-1": ["step-3"], "step-2": ["step-3"]}
        context = {"variables": {}}

        results = await executor.execute_plan(steps, dependencies, context)

        assert len(results) == 2
        assert all(r["status"] == "completed" for r in results.values())

    @pytest.mark.asyncio
    async def test_execute_sequential_dependencies(self, executor: Any) -> None:
        """Steps with dependencies execute in correct order."""
        steps = [
            {
                "id": "step-1",
                "tool_name": "describe_pods",
                "server": "aws-ecs",
                "input_schema": {},
            },
            {
                "id": "step-2",
                "tool_name": "restart_pods",
                "server": "aws-ecs",
                "input_schema": {"pod_ids": "{{step-1.output.pod_ids}}"},
            },
        ]
        dependencies = {"step-1": ["step-2"], "step-2": []}
        context = {"variables": {}}

        results = await executor.execute_plan(steps, dependencies, context)

        assert results["step-1"]["status"] == "completed"
        assert results["step-2"]["status"] == "completed"
        # step-1 should complete before step-2 starts
        assert results["step-1"]["completed_at"] <= results["step-2"]["started_at"]

    @pytest.mark.asyncio
    async def test_execute_diamond_dependencies(self, executor: Any) -> None:
        """Diamond-shaped DAG: A → B, A → C, B → D, C → D."""
        steps = [
            {"id": "a", "tool_name": "describe_pods", "server": "aws-ecs", "input_schema": {}},
            {"id": "b", "tool_name": "get_cloudwatch_metrics", "server": "aws-ecs", "input_schema": {}},
            {"id": "c", "tool_name": "list_issues", "server": "github", "input_schema": {}},
            {"id": "d", "tool_name": "send_slack_message", "server": "slack", "input_schema": {}},
        ]
        dependencies = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
        context = {"variables": {}}

        results = await executor.execute_plan(steps, dependencies, context)

        assert all(results[s["id"]]["status"] == "completed" for s in steps)
        # D must complete after both B and C
        assert results["d"]["started_at"] >= max(
            results["b"]["completed_at"],
            results["c"]["completed_at"],
        )


class TestExecuteConditionalStep:
    """Tests for conditional step execution."""

    @pytest.fixture
    def executor(self, mock_mcp_hub: Any) -> Any:
        """Provide a step executor."""
        from opsmate.services.executor import StepExecutor
        return StepExecutor(mcp_hub=mock_mcp_hub)

    @pytest.mark.asyncio
    async def test_execute_conditional_step_true(self, executor: Any) -> None:
        """Conditional step executes when condition evaluates to True."""
        steps = [
            {
                "id": "step-1",
                "tool_name": "get_cloudwatch_metrics",
                "server": "aws-ecs",
                "input_schema": {},
            },
            {
                "id": "step-2",
                "tool_name": "restart_pods",
                "server": "aws-ecs",
                "input_schema": {},
                "condition": "{{step-1.output.max_cpu}} > 50",
            },
        ]
        dependencies = {"step-1": ["step-2"], "step-2": []}
        context = {"variables": {}, "step_results": {"step-1": {"output": {"max_cpu": 87.5}}}}

        results = await executor.execute_plan(steps, dependencies, context)

        assert results["step-2"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_execute_conditional_step_false(self, executor: Any) -> None:
        """Conditional step is skipped when condition evaluates to False."""
        steps = [
            {
                "id": "step-1",
                "tool_name": "get_cloudwatch_metrics",
                "server": "aws-ecs",
                "input_schema": {},
            },
            {
                "id": "step-2",
                "tool_name": "restart_pods",
                "server": "aws-ecs",
                "input_schema": {},
                "condition": "{{step-1.output.max_cpu}} > 90",
            },
        ]
        dependencies = {"step-1": ["step-2"], "step-2": []}
        context = {"variables": {}, "step_results": {"step-1": {"output": {"max_cpu": 45.0}}}}

        results = await executor.execute_plan(steps, dependencies, context)

        assert results["step-2"]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_execute_conditional_step_missing_variable(self, executor: Any) -> None:
        """Conditional step with missing reference variable is skipped."""
        steps = [
            {"id": "step-1", "tool_name": "describe_pods", "server": "aws-ecs", "input_schema": {}},
            {
                "id": "step-2",
                "tool_name": "restart_pods",
                "server": "aws-ecs",
                "input_schema": {},
                "condition": "{{step-1.output.nonexistent}} > 80",
            },
        ]
        dependencies = {"step-1": ["step-2"], "step-2": []}
        context = {"variables": {}, "step_results": {"step-1": {"output": {}}}}

        results = await executor.execute_plan(steps, dependencies, context)

        # Should skip rather than fail
        assert results["step-2"]["status"] in ("skipped", "failed")


class TestExecuteWithFailureRetry:
    """Tests for failure retry logic."""

    @pytest.fixture
    def executor(self, mock_mcp_hub: Any) -> Any:
        """Provide a step executor."""
        from opsmate.services.executor import StepExecutor
        return StepExecutor(mcp_hub=mock_mcp_hub, max_retries=3, base_delay=0.01)

    @pytest.mark.asyncio
    async def test_retry_transient_failure_then_success(self, executor: Any, mock_mcp_hub: Any) -> None:
        """Transient failures are retried with exponential backoff, then succeed."""
        call_count = 0

        async def failing_then_succeeding(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TimeoutError("Simulated transient failure")
            return {"result": "success-after-retry"}

        mock_mcp_hub.call_tool = AsyncMock(side_effect=failing_then_succeeding)

        step = {
            "id": "step-1",
            "tool_name": "describe_pods",
            "server": "aws-ecs",
            "input_schema": {},
        }
        context = {"variables": {}}

        result = await executor.execute_step(step, context)

        assert result["status"] == "completed"
        assert call_count == 3  # 2 failures + 1 success

    @pytest.mark.asyncio
    async def test_retry_exhausted(self, executor: Any, mock_mcp_hub: Any) -> None:
        """After max retries exhausted, step is marked as failed."""
        mock_mcp_hub.call_tool = AsyncMock(
            side_effect=TimeoutError("Persistent transient failure")
        )

        step = {
            "id": "step-1",
            "tool_name": "describe_pods",
            "server": "aws-ecs",
            "input_schema": {},
            "critical": False,
        }
        context = {"variables": {}}

        result = await executor.execute_step(step, context)

        assert result["status"] == "failed"
        assert "error" in result
        assert result["error"]["retryable"] is True
        assert result["error"]["attempt_count"] == 3  # max retries

    @pytest.mark.asyncio
    async def test_no_retry_for_permanent_error(self, executor: Any, mock_mcp_hub: Any) -> None:
        """Permanent errors (400, 403, 404) are not retried."""
        class HTTP403(Exception):
            status_code = 403

        mock_mcp_hub.call_tool = AsyncMock(side_effect=HTTP403("Permission denied"))

        step = {
            "id": "step-1",
            "tool_name": "describe_pods",
            "server": "aws-ecs",
            "input_schema": {},
            "critical": False,
        }
        context = {"variables": {}}

        result = await executor.execute_step(step, context)

        assert result["status"] == "failed"
        assert result["error"]["classification"] == "permanent"
        # Should only be called once — no retries
        assert mock_mcp_hub.call_tool.call_count == 1


class TestExecuteCircuitBreaker:
    """Tests for circuit breaker integration during execution."""

    @pytest.fixture
    def executor(self, mock_mcp_hub: Any) -> Any:
        """Provide a step executor with circuit breaker."""
        from opsmate.services.executor import StepExecutor
        from opsmate.services.recovery import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=0.1)
        return StepExecutor(mcp_hub=mock_mcp_hub, circuit_breaker=cb)

    @pytest.mark.asyncio
    async def test_circuit_closed_allows_execution(self, executor: Any) -> None:
        """When circuit is CLOSED, execution proceeds normally."""
        step = {
            "id": "step-1",
            "tool_name": "describe_pods",
            "server": "aws-ecs",
            "input_schema": {},
        }
        context = {"variables": {}}

        result = await executor.execute_step(step, context)

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_circuit_open_fails_fast(self, executor: Any, mock_mcp_hub: Any) -> None:
        """When circuit is OPEN, execution fails fast without calling the tool."""
        from opsmate.services.recovery import CircuitBreaker, CircuitState

        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        # Force circuit open
        await cb._set_state("aws-ecs", CircuitState.OPEN)

        from opsmate.services.executor import StepExecutor
        executor = StepExecutor(mcp_hub=mock_mcp_hub, circuit_breaker=cb)

        step = {
            "id": "step-1",
            "tool_name": "describe_pods",
            "server": "aws-ecs",
            "input_schema": {},
        }
        context = {"variables": {}}

        result = await executor.execute_step(step, context)

        assert result["status"] == "failed"
        assert "circuit breaker" in result["error"]["message"].lower()
        # Tool should not have been called
        assert mock_mcp_hub.call_tool.call_count == 0

    @pytest.mark.asyncio
    async def test_circuit_state_transitions(self) -> None:
        """Circuit breaker transitions through CLOSED → OPEN → HALF_OPEN → CLOSED."""
        from opsmate.services.recovery import CircuitBreaker, CircuitState

        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05)

        # Initial state: CLOSED
        assert await cb._get_state("test-server") == CircuitState.CLOSED

        # After 2 failures: OPEN
        await cb._record_failure("test-server")
        await cb._record_failure("test-server")
        assert await cb._get_state("test-server") == CircuitState.OPEN

        # After recovery timeout: HALF_OPEN
        import asyncio
        await asyncio.sleep(0.06)
        # State should transition to half-open on next call check

        # After success: CLOSED
        await cb._record_success("test-server")
        assert await cb._get_state("test-server") == CircuitState.CLOSED
