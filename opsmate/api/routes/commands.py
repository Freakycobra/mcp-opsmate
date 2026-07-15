"""Commands route for mcp-opsmate.

POST /commands -- Submit a new natural language command.
Full implementation with intent classification, plan generation,
and execution orchestration.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from opsmate.core.config import get_config
from opsmate.core.constants import ExecutionStatus, INTENT_CLASSIFICATION_CONFIDENCE_THRESHOLD
from opsmate.core.exceptions import (
    HumanEscalationError,
    IntentClassificationError,
    PlanningError,
)
from opsmate.core.models import (
    ClarificationResponse,
    CommandRequest,
    CommandResponse,
    ExecutionState,
)
from opsmate.infra.llm import LLMClient
from opsmate.infra.mcp_hub import ModeRouter, ToolRegistry
from opsmate.services.audit import AuditLogger
from opsmate.services.executor import StepExecutor
from opsmate.services.intent import IntentClassifier, IntentPlanner
from opsmate.services.state import StateManager

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(tags=["Commands"])

# SSE event queues per execution
_sse_queues: dict[UUID, asyncio.Queue[dict[str, Any]]] = {}


async def _get_sse_queue(execution_id: UUID) -> asyncio.Queue[dict[str, Any]]:
    """Get or create an SSE event queue for an execution."""
    if execution_id not in _sse_queues:
        _sse_queues[execution_id] = asyncio.Queue()
    return _sse_queues[execution_id]


async def _emit_event(execution_id: UUID, event_type: str, data: dict[str, Any]) -> None:
    """Emit an SSE event to the queue."""
    queue: asyncio.Queue[dict[str, Any]] | None = _sse_queues.get(execution_id)
    if queue:
        await queue.put({"event": event_type, "data": data})


@router.post(
    "/commands",
    response_model=CommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        422: {"model": ClarificationResponse, "description": "Low intent confidence"},
        503: {"description": "MCP servers unavailable"},
    },
)
async def submit_command(
    request: Request,
    command_request: CommandRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(),
    state_manager: StateManager = Depends(),
    llm_client: LLMClient = Depends(),
    tool_registry: ToolRegistry = Depends(),
    mode_router: ModeRouter = Depends(),
    audit_logger: AuditLogger = Depends(),
) -> CommandResponse:
    """Submit a natural language command for processing.

    1. Create execution (PENDING)
    2. Classify intent
    3. Generate plan
    4. If multi-step: return plan for confirmation (AWAITING_CONFIRMATION)
    5. If single-step + auto_approve: start executing (EXECUTING)
    6. Background task for execution
    7. Return 202 with execution_id and stream_url
    """
    config = get_config()
    start_time: float = time.perf_counter()

    # Resolve execution mode
    execution_mode: str = command_request.execution_mode_override or config.app.execution_mode

    # Create execution
    state: ExecutionState = state_manager.create_execution(
        command=command_request.text,
        execution_mode=execution_mode,
        metadata=command_request.metadata,
    )

    # Persist execution
    await state_manager.persist_execution(state)

    # Log command receipt
    audit_logger.log_command_received(
        execution_id=str(state.execution_id),
        command=command_request.text,
        execution_mode=execution_mode,
    )

    # Initialize SSE queue
    await _get_sse_queue(state.execution_id)

    # Transition to PLANNING
    state = await state_manager.transition(state, "classify_start")
    await state_manager.update_execution(state)

    # Classify intent
    try:
        classifier: IntentClassifier = IntentClassifier(llm_client)
        intent = await classifier.classify(command_request.text)

        audit_logger.log_intent_classified(
            execution_id=str(state.execution_id),
            intent_types=[t.value for t in intent.intent_types],
            confidence=intent.confidence,
        )

    except IntentClassificationError as e:
        # Return clarification response
        logger.info(
            "Intent clarification needed for execution %s (confidence=%.2f)",
            state.execution_id,
            e.confidence,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ClarificationResponse(
                execution_id=state.execution_id,
                confidence=e.confidence,
                reason=e.reason,
                suggested_rephrasings=e.suggested_rephrasings,
                examples=[
                    "Check payment-service pods in EKS, restart if CPU > 80%",
                    "Find P0 incidents in JIRA from last 24h and post to #incidents",
                    "Compare Lambda costs between us-east-1 and eu-west-1 for the last 7 days",
                ],
            ).model_dump(),
        )

    # Generate plan
    planning_start: float = time.perf_counter()
    try:
        planner: IntentPlanner = IntentPlanner(
            llm_client=llm_client,
            available_tools=tool_registry.get_available_tools_for_planning(),
        )
        plan = await planner.build_plan(intent)

        planning_duration_ms: float = (time.perf_counter() - planning_start) * 1000
        state.planning_duration_ms = planning_duration_ms

        audit_logger.log_plan_generated(
            execution_id=str(state.execution_id),
            plan_id=plan.plan_id,
            template_used=plan.template_used,
            step_count=len(plan.steps),
            risk_level=plan.risk_level.value,
            confidence=plan.confidence,
        )

    except PlanningError as e:
        logger.error("Plan generation failed for execution %s: %s", state.execution_id, e)
        state = await state_manager.transition(state, "plan_error")
        await state_manager.update_execution(state)
        audit_logger.log_execution_failed(
            execution_id=str(state.execution_id),
            failure_reason=f"Plan generation failed: {e.message}",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Plan generation failed: {e.message}",
        )

    # Attach plan to state
    state.plan = plan

    # Determine next step
    is_single_step: bool = len(plan.steps) == 1
    should_auto_approve: bool = is_single_step and command_request.auto_approve

    if should_auto_approve:
        # Auto-approve single-step plan
        state = await state_manager.transition(state, "single_step_auto")
        await state_manager.update_execution(state)

        # Start execution in background
        background_tasks.add_task(
            _execute_plan_background,
            state,
            state_manager,
            mode_router,
            audit_logger,
        )

        return CommandResponse(
            execution_id=state.execution_id,
            status=ExecutionStatus.EXECUTING,
            message="Single-step plan auto-approved, execution started",
            execution_mode=execution_mode,
            stream_url=f"/stream/{state.execution_id}",
        )
    else:
        # Multi-step or no auto-approve: await confirmation
        state = await state_manager.transition(state, "plan_generated")
        await state_manager.update_execution(state)

        # Emit plan event
        await _emit_event(state.execution_id, "plan.generated", plan.model_dump(mode="json"))
        await _emit_event(
            state.execution_id,
            "plan.awaiting_confirmation",
            {
                "execution_id": str(state.execution_id),
                "plan": plan.model_dump(mode="json"),
                "risk_level": plan.risk_level.value,
            },
        )

        return CommandResponse(
            execution_id=state.execution_id,
            status=ExecutionStatus.AWAITING_CONFIRMATION,
            message=f"Plan generated with {len(plan.steps)} steps. Awaiting confirmation.",
            execution_mode=execution_mode,
            stream_url=f"/stream/{state.execution_id}",
        )


async def _execute_plan_background(
    state: ExecutionState,
    state_manager: StateManager,
    mode_router: ModeRouter,
    audit_logger: AuditLogger,
) -> None:
    """Background task to execute a plan.

    Args:
        state: Execution state with plan.
        state_manager: State manager for persistence.
        mode_router: Mode router for tool calls.
        audit_logger: Audit logger.
    """
    execution_id: UUID = state.execution_id
    logger.info("Starting background execution for %s", execution_id)

    async def emit(event_type: str, data: dict[str, Any]) -> None:
        await _emit_event(execution_id, event_type, data)

    try:
        executor: StepExecutor = StepExecutor(
            mode_router=mode_router,
            event_emitter=emit,
        )

        final_state: ExecutionState = await executor.execute_plan(state)

        # Persist final state
        await state_manager.update_execution(final_state)

        # Emit completion event
        if final_state.status == ExecutionStatus.COMPLETED:
            await emit("execution.completed", {
                "execution_id": str(execution_id),
                "status": "completed",
                "summary": f"Execution completed with {len(final_state.results)} steps",
                "result_preview": {
                    step_id: result.output for step_id, result in final_state.results.items()
                    if result.output is not None
                },
                "total_duration_ms": final_state.total_duration_ms,
                "completed_at": datetime.utcnow().isoformat(),
            })
            audit_logger.log_execution_completed(
                execution_id=str(execution_id),
                total_duration_ms=final_state.total_duration_ms,
                step_count=len(final_state.results),
            )
        else:
            await emit("execution.failed", {
                "execution_id": str(execution_id),
                "status": "failed",
                "failure_reason": "One or more steps failed",
                "total_duration_ms": final_state.total_duration_ms,
                "completed_at": datetime.utcnow().isoformat(),
            })
            audit_logger.log_execution_failed(
                execution_id=str(execution_id),
                failure_reason="Step execution failed",
            )

    except HumanEscalationError as e:
        logger.warning("Human escalation for execution %s: %s", execution_id, e.message)
        await state_manager.update_execution(
            state.update_status(ExecutionStatus.PAUSED)
        )
        await emit("escalation.required", {
            "step_id": e.step_id,
            "reason": e.message,
            "options": e.options,
            "timeout_seconds": e.timeout_seconds,
            "impact": e.impact,
        })
        audit_logger.log_escalation_triggered(
            execution_id=str(execution_id),
            step_id=e.step_id or "unknown",
            reason=e.message,
        )

    except Exception as e:
        logger.exception("Background execution failed for %s: %s", execution_id, e)
        await state_manager.update_execution(
            state.update_status(ExecutionStatus.FAILED)
        )
        await emit("execution.failed", {
            "execution_id": str(execution_id),
            "status": "failed",
            "failure_reason": str(e),
            "completed_at": datetime.utcnow().isoformat(),
        })
        audit_logger.log_execution_failed(
            execution_id=str(execution_id),
            failure_reason=str(e),
        )
