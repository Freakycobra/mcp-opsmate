"""
Tests for the state manager service.

Covers execution creation, state machine transitions, step result persistence,
execution listing, and graceful shutdown handling.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from opsmate.core.models import ExecutionStatus


class TestCreateExecution:
    """Tests for creating new executions."""

    @pytest.fixture
    def state_manager(self, test_db: dict[str, str]) -> Any:
        """Provide a state manager connected to the test database."""
        from opsmate.services.state import StateManager
        return StateManager(database_url=test_db["db_url"])

    @pytest.mark.asyncio
    async def test_create_execution(self, state_manager: Any) -> None:
        """Creating an execution returns a valid ExecutionState with PENDING status."""
        command_text = "Check payment-service pods in EKS"
        result = await state_manager.create_execution(command_text)

        assert result["execution_id"] is not None
        assert result["status"] == ExecutionStatus.PENDING.value
        assert result["command_text"] == command_text
        assert result["execution_mode"] == "mock"
        assert "created_at" in result
        assert "updated_at" in result

    @pytest.mark.asyncio
    async def test_create_execution_generates_unique_ids(self, state_manager: Any) -> None:
        """Each execution gets a unique UUID."""
        result1 = await state_manager.create_execution("Command 1")
        result2 = await state_manager.create_execution("Command 2")

        assert result1["execution_id"] != result2["execution_id"]

    @pytest.mark.asyncio
    async def test_create_execution_persists_to_database(
        self,
        state_manager: Any,
        db_session: Any,
    ) -> None:
        """Created execution is persisted to PostgreSQL."""
        result = await state_manager.create_execution("Test command")
        exec_id = result["execution_id"]

        # Verify we can load it from the database
        loaded = await state_manager.get_execution(exec_id)
        assert loaded is not None
        assert loaded["command_text"] == "Test command"
        assert loaded["status"] == ExecutionStatus.PENDING.value


class TestStateTransitions:
    """Tests for the execution state machine transitions."""

    @pytest.fixture
    def state_manager(self, test_db: dict[str, str]) -> Any:
        """Provide a state manager."""
        from opsmate.services.state import StateManager
        return StateManager(database_url=test_db["db_url"])

    @pytest.mark.asyncio
    async def test_pending_to_planning(self, state_manager: Any) -> None:
        """PENDING → PLANNING transition."""
        exec_state = await state_manager.create_execution("Test command")
        exec_id = exec_state["execution_id"]

        result = await state_manager.transition(exec_id, ExecutionStatus.PLANNING)

        assert result["status"] == ExecutionStatus.PLANNING.value

    @pytest.mark.asyncio
    async def test_planning_to_awaiting_confirmation(self, state_manager: Any) -> None:
        """PLANNING → AWAITING_CONFIRMATION transition."""
        exec_state = await state_manager.create_execution("Test command")
        exec_id = exec_state["execution_id"]

        await state_manager.transition(exec_id, ExecutionStatus.PLANNING)
        result = await state_manager.transition(
            exec_id, ExecutionStatus.AWAITING_CONFIRMATION
        )

        assert result["status"] == ExecutionStatus.AWAITING_CONFIRMATION.value

    @pytest.mark.asyncio
    async def test_awaiting_confirmation_to_executing(self, state_manager: Any) -> None:
        """AWAITING_CONFIRMATION → EXECUTING transition on user approval."""
        exec_state = await state_manager.create_execution("Test command")
        exec_id = exec_state["execution_id"]

        await state_manager.transition(exec_id, ExecutionStatus.PLANNING)
        await state_manager.transition(exec_id, ExecutionStatus.AWAITING_CONFIRMATION)
        result = await state_manager.transition(exec_id, ExecutionStatus.EXECUTING)

        assert result["status"] == ExecutionStatus.EXECUTING.value

    @pytest.mark.asyncio
    async def test_executing_to_completed(self, state_manager: Any) -> None:
        """EXECUTING → COMPLETED transition."""
        exec_state = await state_manager.create_execution("Test command")
        exec_id = exec_state["execution_id"]

        await state_manager.transition(exec_id, ExecutionStatus.PLANNING)
        await state_manager.transition(exec_id, ExecutionStatus.AWAITING_CONFIRMATION)
        await state_manager.transition(exec_id, ExecutionStatus.EXECUTING)
        result = await state_manager.transition(exec_id, ExecutionStatus.COMPLETED)

        assert result["status"] == ExecutionStatus.COMPLETED.value
        assert result["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_executing_to_failed(self, state_manager: Any) -> None:
        """EXECUTING → FAILED transition on critical step failure."""
        exec_state = await state_manager.create_execution("Test command")
        exec_id = exec_state["execution_id"]

        await state_manager.transition(exec_id, ExecutionStatus.PLANNING)
        await state_manager.transition(exec_id, ExecutionStatus.AWAITING_CONFIRMATION)
        await state_manager.transition(exec_id, ExecutionStatus.EXECUTING)
        result = await state_manager.transition(exec_id, ExecutionStatus.FAILED)

        assert result["status"] == ExecutionStatus.FAILED.value

    @pytest.mark.asyncio
    async def test_awaiting_confirmation_to_cancelled(self, state_manager: Any) -> None:
        """AWAITING_CONFIRMATION → CANCELLED transition on user rejection."""
        exec_state = await state_manager.create_execution("Test command")
        exec_id = exec_state["execution_id"]

        await state_manager.transition(exec_id, ExecutionStatus.PLANNING)
        await state_manager.transition(exec_id, ExecutionStatus.AWAITING_CONFIRMATION)
        result = await state_manager.transition(exec_id, ExecutionStatus.CANCELLED)

        assert result["status"] == ExecutionStatus.CANCELLED.value

    @pytest.mark.asyncio
    async def test_executing_to_paused(self, state_manager: Any) -> None:
        """EXECUTING → PAUSED transition on human escalation."""
        exec_state = await state_manager.create_execution("Test command")
        exec_id = exec_state["execution_id"]

        await state_manager.transition(exec_id, ExecutionStatus.PLANNING)
        await state_manager.transition(exec_id, ExecutionStatus.AWAITING_CONFIRMATION)
        await state_manager.transition(exec_id, ExecutionStatus.EXECUTING)
        result = await state_manager.transition(exec_id, ExecutionStatus.PAUSED)

        assert result["status"] == ExecutionStatus.PAUSED.value

    @pytest.mark.asyncio
    async def test_paused_to_executing(self, state_manager: Any) -> None:
        """PAUSED → EXECUTING transition on user continue."""
        exec_state = await state_manager.create_execution("Test command")
        exec_id = exec_state["execution_id"]

        await state_manager.transition(exec_id, ExecutionStatus.PLANNING)
        await state_manager.transition(exec_id, ExecutionStatus.AWAITING_CONFIRMATION)
        await state_manager.transition(exec_id, ExecutionStatus.EXECUTING)
        await state_manager.transition(exec_id, ExecutionStatus.PAUSED)
        result = await state_manager.transition(exec_id, ExecutionStatus.EXECUTING)

        assert result["status"] == ExecutionStatus.EXECUTING.value

    @pytest.mark.asyncio
    async def test_invalid_transition_blocked(self, state_manager: Any) -> None:
        """Invalid state transitions are rejected."""
        exec_state = await state_manager.create_execution("Test command")
        exec_id = exec_state["execution_id"]

        # Cannot go directly from PENDING to COMPLETED
        with pytest.raises(Exception):
            await state_manager.transition(exec_id, ExecutionStatus.COMPLETED)


class TestPersistStepResult:
    """Tests for persisting step results."""

    @pytest.fixture
    def state_manager(self, test_db: dict[str, str]) -> Any:
        """Provide a state manager."""
        from opsmate.services.state import StateManager
        return StateManager(database_url=test_db["db_url"])

    @pytest.mark.asyncio
    async def test_persist_step_result(self, state_manager: Any) -> None:
        """Step results are persisted and can be retrieved."""
        exec_state = await state_manager.create_execution("Test command")
        exec_id = exec_state["execution_id"]

        step_result = {
            "step_id": "step-1",
            "tool_name": "describe_pods",
            "server": "aws-ecs",
            "status": "completed",
            "output": {"pods": [{"name": "pod-1", "status": "Running"}]},
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }

        await state_manager.persist_step_result(exec_id, step_result)

        # Verify the result is persisted
        loaded = await state_manager.get_execution(exec_id)
        assert "step-1" in loaded["results"]
        assert loaded["results"]["step-1"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_persist_multiple_step_results(self, state_manager: Any) -> None:
        """Multiple step results are accumulated."""
        exec_state = await state_manager.create_execution("Test command")
        exec_id = exec_state["execution_id"]

        for i in range(3):
            step_result = {
                "step_id": f"step-{i+1}",
                "tool_name": "describe_pods",
                "server": "aws-ecs",
                "status": "completed",
                "output": {"index": i},
                "started_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            }
            await state_manager.persist_step_result(exec_id, step_result)

        loaded = await state_manager.get_execution(exec_id)
        assert len(loaded["results"]) == 3

    @pytest.mark.asyncio
    async def test_persist_failed_step_result(self, state_manager: Any) -> None:
        """Failed step results with error details are persisted."""
        exec_state = await state_manager.create_execution("Test command")
        exec_id = exec_state["execution_id"]

        step_result = {
            "step_id": "step-1",
            "tool_name": "restart_pods",
            "server": "aws-ecs",
            "status": "failed",
            "output": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": {
                "classification": "transient",
                "message": "Connection timeout",
                "retryable": True,
                "attempt_count": 3,
            },
        }

        await state_manager.persist_step_result(exec_id, step_result)

        loaded = await state_manager.get_execution(exec_id)
        assert loaded["results"]["step-1"]["status"] == "failed"
        assert loaded["results"]["step-1"]["error"]["classification"] == "transient"


class TestListExecutions:
    """Tests for listing and querying executions."""

    @pytest.fixture
    def state_manager(self, test_db: dict[str, str]) -> Any:
        """Provide a state manager."""
        from opsmate.services.state import StateManager
        return StateManager(database_url=test_db["db_url"])

    @pytest.mark.asyncio
    async def test_list_executions(self, state_manager: Any) -> None:
        """List executions returns paginated results."""
        # Create a few executions
        for i in range(5):
            await state_manager.create_execution(f"Command {i}")

        results = await state_manager.list_executions(page=1, page_size=10)

        assert results["total"] >= 5
        assert len(results["items"]) >= 5
        assert results["page"] == 1
        assert results["page_size"] == 10

    @pytest.mark.asyncio
    async def test_list_executions_with_status_filter(self, state_manager: Any) -> None:
        """Filter executions by status."""
        exec_state = await state_manager.create_execution("Test command")
        exec_id = exec_state["execution_id"]
        await state_manager.transition(exec_id, ExecutionStatus.COMPLETED)

        results = await state_manager.list_executions(
            page=1, page_size=10, status=ExecutionStatus.COMPLETED
        )

        assert all(item["status"] == ExecutionStatus.COMPLETED.value for item in results["items"])

    @pytest.mark.asyncio
    async def test_list_executions_pagination(self, state_manager: Any) -> None:
        """Pagination returns correct page of results."""
        for i in range(15):
            await state_manager.create_execution(f"Command {i}")

        page1 = await state_manager.list_executions(page=1, page_size=10)
        page2 = await state_manager.list_executions(page=2, page_size=10)

        assert len(page1["items"]) == 10
        assert len(page2["items"]) >= 5


class TestGracefulShutdown:
    """Tests for graceful shutdown handling."""

    @pytest.fixture
    def state_manager(self, test_db: dict[str, str]) -> Any:
        """Provide a state manager."""
        from opsmate.services.state import StateManager
        return StateManager(database_url=test_db["db_url"])

    @pytest.mark.asyncio
    async def test_graceful_shutdown_persists_in_flight(self, state_manager: Any) -> None:
        """On shutdown signal, in-flight executions are persisted."""
        exec_state = await state_manager.create_execution("Long running command")
        exec_id = exec_state["execution_id"]

        await state_manager.transition(exec_id, ExecutionStatus.PLANNING)
        await state_manager.transition(exec_id, ExecutionStatus.AWAITING_CONFIRMATION)
        await state_manager.transition(exec_id, ExecutionStatus.EXECUTING)

        # Simulate graceful shutdown
        await state_manager.handle_shutdown()

        # Verify execution state is persisted
        loaded = await state_manager.get_execution(exec_id)
        assert loaded["status"] == ExecutionStatus.EXECUTING.value

    @pytest.mark.asyncio
    async def test_resume_after_shutdown(self, state_manager: Any) -> None:
        """After restart, incomplete executions can be resumed."""
        exec_state = await state_manager.create_execution("Resumable command")
        exec_id = exec_state["execution_id"]

        await state_manager.transition(exec_id, ExecutionStatus.PLANNING)
        await state_manager.transition(exec_id, ExecutionStatus.EXECUTING)

        # Simulate shutdown and restart
        await state_manager.handle_shutdown()

        # Resume incomplete executions
        incomplete = await state_manager.get_incomplete_executions()
        assert any(e["execution_id"] == exec_id for e in incomplete)

    @pytest.mark.asyncio
    async def test_graceful_shutdown_timeout(self, state_manager: Any) -> None:
        """Shutdown respects timeout for in-flight steps."""
        exec_state = await state_manager.create_execution("Slow command")
        exec_id = exec_state["execution_id"]

        await state_manager.transition(exec_id, ExecutionStatus.EXECUTING)

        # Shutdown with short timeout should complete within time
        import asyncio
        await asyncio.wait_for(state_manager.handle_shutdown(), timeout=5.0)

        loaded = await state_manager.get_execution(exec_id)
        assert loaded is not None
