"""State manager service for mcp-opsmate.

Manages execution lifecycle: create, transition, persist, and retrieve
execution states. Integrates with the state machine for valid transitions.
"""

from __future__ import annotations

import logging
import signal
from datetime import datetime
from typing import Any, AsyncGenerator
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opsmate.core.config import get_config
from opsmate.core.constants import ExecutionStatus
from opsmate.core.exceptions import StateTransitionError
from opsmate.core.models import (
    AuditLogEntry,
    ExecutionContext,
    ExecutionPlan,
    ExecutionState,
    StepResult,
)
from opsmate.core.state_machine import get_state_machine
from opsmate.infra.database import (
    AuditLog as AuditLogORM,
    Execution as ExecutionORM,
    StepResult as StepResultORM,
    get_db_session,
)

logger: logging.Logger = logging.getLogger(__name__)


class StateManager:
    """Manages execution state persistence and transitions.

    Integrates with PostgreSQL for durable state storage and the
    state machine for valid transition enforcement.
    """

    def __init__(self, db_session: AsyncSession | None = None) -> None:
        self._db: AsyncSession | None = db_session
        self._state_machine = get_state_machine()
        self._config = get_config()
        self._shutdown_event: asyncio.Event | None = None

    @property
    def db(self) -> AsyncSession:
        if self._db is None:
            raise RuntimeError("No database session available")
        return self._db

    def set_db_session(self, session: AsyncSession) -> None:
        """Set the database session."""
        self._db = session

    def create_execution(
        self,
        command: str,
        execution_mode: str = "mock",
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionState:
        """Create a new execution in PENDING state.

        Args:
            command: The natural language command.
            execution_mode: Execution mode (mock/live/mixed).
            metadata: Optional client metadata.

        Returns:
            New ExecutionState with PENDING status.
        """
        execution_id: UUID = uuid4()
        context: ExecutionContext = ExecutionContext(
            metadata=metadata or {},
            secrets_redacted=True,
        )

        state: ExecutionState = ExecutionState(
            execution_id=execution_id,
            status=ExecutionStatus.PENDING,
            command_text=command,
            execution_mode=execution_mode,
            context=context,
        )

        logger.info("Created execution %s for command: %s", execution_id, command[:100])
        return state

    async def persist_execution(self, state: ExecutionState) -> None:
        """Persist an execution state to the database.

        Args:
            state: The execution state to persist.
        """
        plan_data: dict[str, Any] | None = None
        if state.plan:
            plan_data = state.plan.model_dump(mode="json")

        results_data: dict[str, Any] = {}
        for step_id, result in state.results.items():
            results_data[step_id] = result.model_dump(mode="json")

        orm_execution: ExecutionORM = ExecutionORM(
            execution_id=state.execution_id,
            status=state.status.value,
            command_text=state.command_text,
            plan=plan_data,
            results=results_data,
            context=state.context.model_dump(mode="json"),
            execution_mode=state.execution_mode,
            created_at=state.created_at,
            updated_at=datetime.utcnow(),
            completed_at=state.completed_at,
            planning_duration_ms=state.planning_duration_ms,
            total_duration_ms=state.total_duration_ms,
        )

        self.db.add(orm_execution)
        await self.db.commit()
        logger.debug("Persisted execution %s", state.execution_id)

    async def update_execution(self, state: ExecutionState) -> None:
        """Update an existing execution in the database.

        Args:
            state: The updated execution state.
        """
        result = await self.db.execute(
            select(ExecutionORM).where(
                ExecutionORM.execution_id == state.execution_id
            )
        )
        orm_execution: ExecutionORM | None = result.scalar_one_or_none()
        if orm_execution is None:
            await self.persist_execution(state)
            return

        # Update fields
        orm_execution.status = state.status.value
        orm_execution.updated_at = datetime.utcnow()

        if state.plan:
            orm_execution.plan = state.plan.model_dump(mode="json")

        results_data: dict[str, Any] = {}
        for step_id, result in state.results.items():
            results_data[step_id] = result.model_dump(mode="json")
        orm_execution.results = results_data

        orm_execution.context = state.context.model_dump(mode="json")
        orm_execution.completed_at = state.completed_at
        orm_execution.planning_duration_ms = state.planning_duration_ms
        orm_execution.total_duration_ms = state.total_duration_ms

        await self.db.commit()
        logger.debug("Updated execution %s (status=%s)", state.execution_id, state.status.value)

    async def transition(
        self,
        state: ExecutionState,
        event: str,
    ) -> ExecutionState:
        """Apply a state transition with validation.

        Args:
            state: Current execution state.
            event: Transition event name.

        Returns:
            Updated execution state with new status.

        Raises:
            StateTransitionError: If the transition is invalid.
        """
        new_status: ExecutionStatus = self._state_machine.transition(
            state.status, event
        )

        old_status: ExecutionStatus = state.status
        updated_state: ExecutionState = state.update_status(new_status)

        # Auto-set completed_at for terminal states
        if self._state_machine.is_terminal(new_status):
            updated_state.completed_at = datetime.utcnow()
            updated_state.total_duration_ms = (
                updated_state.completed_at - updated_state.created_at
            ).total_seconds() * 1000

        logger.info(
            "Execution %s: %s -> %s (event=%s)",
            state.execution_id,
            old_status.value,
            new_status.value,
            event,
        )

        return updated_state

    async def persist_step_result(
        self,
        execution_id: UUID,
        step_result: StepResult,
    ) -> None:
        """Persist a step result to the database.

        Args:
            execution_id: The execution ID.
            step_result: The step result to persist.
        """
        # Upsert: check if step result already exists
        result = await self.db.execute(
            select(StepResultORM).where(
                StepResultORM.execution_id == execution_id,
                StepResultORM.step_id == step_result.step_id,
            )
        )
        existing: StepResultORM | None = result.scalar_one_or_none()

        if existing:
            existing.status = step_result.status.value
            existing.output = step_result.output if isinstance(step_result.output, dict) else None
            existing.error = step_result.error.model_dump(mode="json") if step_result.error else None
            existing.attempt_count = step_result.attempt_count
            existing.started_at = step_result.started_at
            existing.completed_at = step_result.completed_at
        else:
            orm_result: StepResultORM = StepResultORM(
                execution_id=execution_id,
                step_id=step_result.step_id,
                tool_name=step_result.tool_name,
                server_name=step_result.server_name,
                status=step_result.status.value,
                output=step_result.output if isinstance(step_result.output, dict) else None,
                error=step_result.error.model_dump(mode="json") if step_result.error else None,
                attempt_count=step_result.attempt_count,
                started_at=step_result.started_at,
                completed_at=step_result.completed_at,
            )
            self.db.add(orm_result)

        await self.db.commit()
        logger.debug(
            "Persisted step result: %s/%s = %s",
            execution_id,
            step_result.step_id,
            step_result.status.value,
        )

    async def get_execution(self, execution_id: UUID) -> ExecutionState | None:
        """Retrieve a full execution state by ID.

        Args:
            execution_id: The execution UUID.

        Returns:
            ExecutionState or None if not found.
        """
        result = await self.db.execute(
            select(ExecutionORM).where(
                ExecutionORM.execution_id == execution_id
            )
        )
        orm_execution: ExecutionORM | None = result.scalar_one_or_none()
        if orm_execution is None:
            return None

        return self._orm_to_state(orm_execution)

    async def list_executions(
        self,
        *,
        status: ExecutionStatus | None = None,
        execution_mode: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
        sort: str = "-created_at",
    ) -> tuple[list[ExecutionState], int]:
        """List executions with filtering and pagination.

        Args:
            status: Filter by execution status.
            execution_mode: Filter by execution mode.
            from_date: Filter from date.
            to_date: Filter to date.
            page: Page number (1-indexed).
            page_size: Items per page.
            sort: Sort field, prefix '-' for descending.

        Returns:
            Tuple of (list of ExecutionState, total count).
        """
        query = select(ExecutionORM)

        if status:
            query = query.where(ExecutionORM.status == status.value)
        if execution_mode:
            query = query.where(ExecutionORM.execution_mode == execution_mode)
        if from_date:
            query = query.where(ExecutionORM.created_at >= from_date)
        if to_date:
            query = query.where(ExecutionORM.created_at <= to_date)

        # Count total
        count_result = await self.db.execute(
            select(ExecutionORM.execution_id).select_from(query.subquery())
        )
        total: int = len(count_result.all())

        # Sort
        sort_field: str = sort.lstrip("-")
        sort_desc: bool = sort.startswith("-")
        orm_field = getattr(ExecutionORM, sort_field, ExecutionORM.created_at)
        if sort_desc:
            query = query.order_by(orm_field.desc())
        else:
            query = query.order_by(orm_field.asc())

        # Paginate
        offset: int = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        executions: list[ExecutionORM] = result.scalars().all()

        states: list[ExecutionState] = [self._orm_to_state(e) for e in executions]
        return states, total

    async def get_audit_log(
        self,
        execution_id: UUID,
    ) -> list[AuditLogEntry]:
        """Get audit log entries for an execution.

        Args:
            execution_id: The execution UUID.

        Returns:
            List of audit log entries.
        """
        result = await self.db.execute(
            select(AuditLogORM)
            .where(AuditLogORM.execution_id == execution_id)
            .order_by(AuditLogORM.timestamp)
        )
        logs: list[AuditLogORM] = result.scalars().all()

        return [
            AuditLogEntry(
                id=log.id,
                execution_id=log.execution_id,
                action=log.action,
                details=log.details,
                user_id=log.user_id,
                timestamp=log.timestamp,
            )
            for log in logs
        ]

    async def add_audit_log(
        self,
        execution_id: UUID | None,
        action: str,
        details: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> AuditLogEntry:
        """Add an audit log entry.

        Args:
            execution_id: The execution UUID (None for system events).
            action: Action type string.
            details: Action-specific details.
            user_id: User identifier.

        Returns:
            The created audit log entry.
        """
        entry: AuditLogEntry = AuditLogEntry(
            id=uuid4(),
            execution_id=execution_id,
            action=action,
            details=details or {},
            user_id=user_id,
        )

        orm_log: AuditLogORM = AuditLogORM(
            id=entry.id,
            execution_id=entry.execution_id,
            action=entry.action,
            details=entry.details,
            user_id=entry.user_id,
            timestamp=entry.timestamp,
        )
        self.db.add(orm_log)
        await self.db.commit()

        logger.debug("Audit log: %s for execution %s", action, execution_id)
        return entry

    def _orm_to_state(self, orm: ExecutionORM) -> ExecutionState:
        """Convert an ORM execution to a domain ExecutionState."""
        plan: ExecutionPlan | None = None
        if orm.plan:
            plan = ExecutionPlan.model_validate(orm.plan)

        results: dict[str, StepResult] = {}
        if orm.results:
            for step_id, result_data in orm.results.items():
                if isinstance(result_data, dict):
                    results[step_id] = StepResult.model_validate(result_data)

        context: ExecutionContext = ExecutionContext()
        if orm.context:
            context = ExecutionContext.model_validate(orm.context)

        return ExecutionState(
            execution_id=orm.execution_id,
            status=ExecutionStatus(orm.status),
            command_text=orm.command_text,
            execution_mode=orm.execution_mode,
            plan=plan,
            results=results,
            context=context,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            completed_at=orm.completed_at,
            planning_duration_ms=orm.planning_duration_ms,
            total_duration_ms=orm.total_duration_ms,
        )

    def setup_graceful_shutdown(self) -> None:
        """Register SIGTERM handler for graceful shutdown."""
        import asyncio

        self._shutdown_event = asyncio.Event()

        def _handle_sigterm(signum: int, frame: Any) -> None:
            logger.info("SIGTERM received, initiating graceful shutdown")
            if self._shutdown_event:
                self._shutdown_event.set()

        signal.signal(signal.SIGTERM, _handle_sigterm)
        logger.info("Graceful shutdown handler registered")

    def is_shutting_down(self) -> bool:
        """Check if a shutdown signal has been received."""
        return self._shutdown_event.is_set() if self._shutdown_event else False


# Convenience: create with database session
import asyncio


async def create_state_manager(db_session: AsyncSession) -> StateManager:
    """Factory to create a StateManager with a database session."""
    manager: StateManager = StateManager(db_session)
    return manager
