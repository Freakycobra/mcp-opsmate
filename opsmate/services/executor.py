"""Step executor service for mcp-opsmate.

Uses asyncio.TaskGroup for structured concurrency with topological sorting,
parallel execution of independent steps, and conditional step execution.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, AsyncGenerator, Callable

from opsmate.core.config import get_config
from opsmate.core.constants import StepStatus
from opsmate.core.exceptions import ExecutionError, HumanEscalationError
from opsmate.core.models import (
    ExecutionContext,
    ExecutionPlan,
    ExecutionState,
    PlanStep,
    StepError,
    StepResult,
)
from opsmate.infra.mcp_hub import ModeRouter

logger: logging.Logger = logging.getLogger(__name__)


class StepExecutor:
    """Executes execution plans using asyncio.TaskGroup.

    Provides:
    - Topological sort for dependency ordering
    - Parallel execution of independent steps
    - Conditional step execution (Jinja2-like condition evaluation)
    - Per-step context passing with schema validation
    - SSE event emission after each step
    """

    def __init__(
        self,
        mode_router: ModeRouter,
        event_emitter: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self._router: ModeRouter = mode_router
        self._event_emitter: Callable[[str, dict[str, Any]], Any] | None = event_emitter
        self._config = get_config()

    async def execute_plan(
        self,
        execution_state: ExecutionState,
    ) -> ExecutionState:
        """Execute a full plan and return the updated state.

        Uses topological sorting to determine step order, then executes
        steps in parallel where possible using asyncio.TaskGroup.

        Args:
            execution_state: Current execution state with plan.

        Returns:
            Updated execution state with all step results.
        """
        if execution_state.plan is None:
            raise ExecutionError("No plan to execute")

        plan: ExecutionPlan = execution_state.plan
        context: ExecutionContext = execution_state.context

        # Compute in-degrees for topological sort
        in_degree: dict[str, int] = {}
        for step in plan.steps:
            in_degree[step.id] = len(step.depends_on)

        # Track completed steps
        completed: dict[str, StepResult] = dict(execution_state.results)
        running: set[str] = set()

        # Create result queue for TaskGroup coordination
        result_queue: asyncio.Queue[StepResult] = asyncio.Queue()

        async def _execute_step(step_id: str) -> None:
            """Execute a single step and put result on queue."""
            step: PlanStep | None = plan.get_step(step_id)
            if step is None:
                logger.error("Step %s not found in plan", step_id)
                await result_queue.put(StepResult(
                    step_id=step_id,
                    status=StepStatus.FAILED,
                    tool_name="unknown",
                    server_name="unknown",
                    error=StepError(
                        classification="configuration",
                        message=f"Step {step_id} not found in plan",
                        retryable=False,
                    ),
                ))
                return

            result: StepResult = await self._execute_single_step(
                step, context, execution_state.command_text
            )
            await result_queue.put(result)

        try:
            async with asyncio.TaskGroup() as tg:
                # Start with zero-dependency steps
                ready: list[str] = [
                    step_id for step_id, deg in in_degree.items() if deg == 0
                ]
                for step_id in ready:
                    if step_id not in completed:
                        running.add(step_id)
                        tg.create_task(_execute_step(step_id))

                # Process results and enqueue dependents
                while len(completed) < len(plan.steps):
                    result: StepResult = await result_queue.get()
                    completed[result.step_id] = result
                    running.discard(result.step_id)

                    # Update context with step output
                    if result.output is not None:
                        context = context.with_variable(result.step_id, result.output)

                    # Emit SSE event
                    await self._emit_step_event(result)

                    # Check for critical failure
                    if result.status == StepStatus.FAILED:
                        step: PlanStep | None = plan.get_step(result.step_id)
                        if step and step.critical:
                            logger.error(
                                "Critical step %s failed, aborting execution",
                                result.step_id,
                            )
                            raise HumanEscalationError(
                                f"Critical step '{result.step_id}' failed",
                                step_id=result.step_id,
                                impact=f"Downstream steps depend on {result.step_id}",
                                options=["retry", "skip", "abort"],
                            )

                    # Enqueue dependents
                    for dependent in plan.dependencies.get(result.step_id, []):
                        in_degree[dependent] -= 1
                        if in_degree[dependent] == 0 and dependent not in completed:
                            dep_step: PlanStep | None = plan.get_step(dependent)
                            if dep_step and dep_step.condition:
                                should_run: bool = self._evaluate_condition(
                                    dep_step.condition, completed
                                )
                                if not should_run:
                                    logger.info(
                                        "Skipping step %s (condition false: %s)",
                                        dependent,
                                        dep_step.condition,
                                    )
                                    completed[dependent] = StepResult(
                                        step_id=dependent,
                                        status=StepStatus.SKIPPED,
                                        tool_name=dep_step.tool_name,
                                        server_name=dep_step.server,
                                    )
                                    await self._emit_step_event(completed[dependent])
                                    continue

                            running.add(dependent)
                            tg.create_task(_execute_step(dependent))

        except ExceptionGroup as eg:
            for e in eg.exceptions:
                if isinstance(e, HumanEscalationError):
                    raise e
            raise ExecutionError(f"Execution failed: {eg}")

        # Build final state
        final_state: ExecutionState = execution_state.model_copy(update={
            "results": completed,
            "context": context,
            "completed_at": datetime.utcnow(),
        })

        # Determine final status
        all_success: bool = all(
            r.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
            for r in completed.values()
        )
        if all_success:
            final_state = final_state.update_status(
                __import__("opsmate.core.constants", fromlist=["ExecutionStatus"]).ExecutionStatus.COMPLETED
            )
        else:
            has_failed: bool = any(
                r.status == StepStatus.FAILED for r in completed.values()
            )
            if has_failed:
                final_state = final_state.update_status(
                    __import__("opsmate.core.constants", fromlist=["ExecutionStatus"]).ExecutionStatus.FAILED
                )

        # Calculate total duration
        if final_state.completed_at:
            final_state.total_duration_ms = (
                final_state.completed_at - final_state.created_at
            ).total_seconds() * 1000

        return final_state

    async def _execute_single_step(
        self,
        step: PlanStep,
        context: ExecutionContext,
        command_text: str,
    ) -> StepResult:
        """Execute a single plan step.

        Args:
            step: The plan step to execute.
            context: Current execution context.
            command_text: Original command for mock seeding.

        Returns:
            StepResult with output or error.
        """
        started_at: datetime = datetime.utcnow()

        # Emit started event
        await self._emit_event("step.started", {
            "step_id": step.id,
            "tool_name": step.tool_name,
            "server": step.server,
            "started_at": started_at.isoformat(),
        })

        try:
            # Resolve input mapping from context
            arguments: dict[str, Any] = self._resolve_input_mapping(
                step.input_mapping, context
            )

            # Route tool call through ModeRouter
            result: Any = await self._router.route_tool_call(
                server_name=step.server,
                tool_name=step.tool_name,
                arguments=arguments,
                command_text=command_text,
            )

            completed_at: datetime = datetime.utcnow()
            duration_ms: float = (completed_at - started_at).total_seconds() * 1000

            logger.info(
                "Step %s completed: %s/%s in %.1fms",
                step.id,
                step.server,
                step.tool_name,
                duration_ms,
            )

            return StepResult(
                step_id=step.id,
                status=StepStatus.COMPLETED,
                tool_name=step.tool_name,
                server_name=step.server,
                output=result if isinstance(result, dict) else {"result": str(result)},
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
            )

        except Exception as e:
            completed_at = datetime.utcnow()
            duration_ms = (completed_at - started_at).total_seconds() * 1000

            logger.error(
                "Step %s failed: %s/%s - %s",
                step.id,
                step.server,
                step.tool_name,
                e,
            )

            return StepResult(
                step_id=step.id,
                status=StepStatus.FAILED,
                tool_name=step.tool_name,
                server_name=step.server,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                error=StepError(
                    classification="transient",
                    message=str(e),
                    retryable=True,
                    server_name=step.server,
                    tool_name=step.tool_name,
                ),
            )

    def _resolve_input_mapping(
        self,
        mapping: dict[str, str],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """Resolve Jinja2-like input mappings from context variables.

        Supports: {{step_id.output_field}} and {{context.variable_name}}
        """
        resolved: dict[str, Any] = {}
        for param, template in mapping.items():
            if template.startswith("{{") and template.endswith("}}"):
                path: str = template[2:-2].strip()
                value: Any = context.get_variable(path)
                if value is not None:
                    resolved[param] = value
                else:
                    resolved[param] = template  # Keep template if not resolved
            else:
                resolved[param] = template
        return resolved

    def _evaluate_condition(
        self,
        condition: str,
        completed_results: dict[str, StepResult],
    ) -> bool:
        """Evaluate a Jinja2-like condition against completed step results.

        Supports simple conditions like '{{step-3.triggered}}' or
        literal 'true'/'false'.
        """
        condition = condition.strip()

        # Literal boolean
        if condition.lower() == "true":
            return True
        if condition.lower() == "false":
            return False

        # Template reference: {{step_id.field}}
        if condition.startswith("{{") and condition.endswith("}}"):
            path: str = condition[2:-2].strip()
            parts: list[str] = path.split(".")
            if len(parts) >= 2:
                step_id: str = parts[0]
                field: str = parts[1]
                result: StepResult | None = completed_results.get(step_id)
                if result and result.output and isinstance(result.output, dict):
                    value: Any = result.output.get(field)
                    return bool(value)

        # Default: evaluate as truthy
        return bool(condition)

    async def _emit_step_event(self, result: StepResult) -> None:
        """Emit SSE event for a step result."""
        if result.status == StepStatus.COMPLETED:
            await self._emit_event("step.completed", {
                "step_id": result.step_id,
                "tool_name": result.tool_name,
                "server": result.server_name,
                "status": "completed",
                "output_preview": str(result.output)[:500] if result.output else "",
                "started_at": result.started_at.isoformat() if result.started_at else None,
                "completed_at": result.completed_at.isoformat() if result.completed_at else None,
                "duration_ms": result.duration_ms,
            })
        elif result.status == StepStatus.FAILED:
            await self._emit_event("step.failed", {
                "step_id": result.step_id,
                "tool_name": result.tool_name,
                "server": result.server_name,
                "status": "failed",
                "error_classification": result.error.classification.value if result.error else "unknown",
                "error_message": result.error.message if result.error else "Unknown error",
                "retryable": result.error.retryable if result.error else False,
                "attempt_count": result.attempt_count,
                "started_at": result.started_at.isoformat() if result.started_at else None,
                "completed_at": result.completed_at.isoformat() if result.completed_at else None,
            })
        elif result.status == StepStatus.SKIPPED:
            await self._emit_event("step.skipped", {
                "step_id": result.step_id,
                "reason": "Condition evaluated to false",
            })

    async def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an SSE event if emitter is configured."""
        if self._event_emitter:
            try:
                await self._event_emitter(event_type, data)
            except Exception:
                logger.exception("Failed to emit SSE event: %s", event_type)
