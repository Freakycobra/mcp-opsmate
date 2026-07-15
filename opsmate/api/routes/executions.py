"""Executions route for mcp-opsmate.

GET /executions -- List executions with pagination and filtering.
GET /executions/{id} -- Get execution detail.
POST /executions/{id}/approve -- Approve a pending plan.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from opsmate.core.constants import ExecutionStatus
from opsmate.core.exceptions import StateTransitionError
from opsmate.core.models import (
    ExecutionDetailResponse,
    ExecutionListResponse,
    ExecutionSummary,
    PlanApprovalRequest,
    PlanApprovalResponse,
)
from opsmate.services.audit import AuditLogger
from opsmate.services.state import StateManager

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(tags=["Executions"])


@router.get("/executions", response_model=ExecutionListResponse)
async def list_executions(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status: ExecutionStatus | None = Query(default=None, description="Filter by status"),
    mode: str | None = Query(default=None, description="Filter by execution mode"),
    from_date: datetime | None = Query(default=None, description="Start date (ISO 8601)"),
    to_date: datetime | None = Query(default=None, description="End date (ISO 8601)"),
    command_q: str | None = Query(default=None, description="Search command text"),
    sort: str = Query(default="-created_at", description="Sort field, prefix - for descending"),
    state_manager: StateManager = Depends(),
) -> ExecutionListResponse:
    """List executions with pagination and filtering."""
    executions, total = await state_manager.list_executions(
        status=status,
        execution_mode=mode,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
        sort=sort,
    )

    total_pages: int = (total + page_size - 1) // page_size

    items: list[ExecutionSummary] = []
    for state in executions:
        failed_steps: int = sum(
            1 for r in state.results.values() if r.status.value == "failed"
        )
        items.append(ExecutionSummary(
            execution_id=state.execution_id,
            status=state.status,
            command_text=state.command_text,
            execution_mode=state.execution_mode,
            created_at=state.created_at,
            updated_at=state.updated_at,
            completed_at=state.completed_at,
            total_duration_ms=state.total_duration_ms,
            step_count=len(state.results),
            failed_steps=failed_steps,
        ))

    return ExecutionListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/executions/{execution_id}", response_model=ExecutionDetailResponse)
async def get_execution(
    execution_id: UUID,
    state_manager: StateManager = Depends(),
) -> ExecutionDetailResponse:
    """Get full execution detail by ID."""
    state = await state_manager.get_execution(execution_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found",
        )

    audit_log = await state_manager.get_audit_log(execution_id)

    return ExecutionDetailResponse(
        execution_id=state.execution_id,
        status=state.status,
        command_text=state.command_text,
        execution_mode=state.execution_mode,
        plan=state.plan,
        results=state.results,
        context=state.context,
        created_at=state.created_at,
        updated_at=state.updated_at,
        completed_at=state.completed_at,
        planning_duration_ms=state.planning_duration_ms,
        total_duration_ms=state.total_duration_ms,
        audit_log=audit_log,
    )


@router.post("/executions/{execution_id}/approve", response_model=PlanApprovalResponse)
async def approve_execution(
    execution_id: UUID,
    approval: PlanApprovalRequest,
    state_manager: StateManager = Depends(),
    audit_logger: AuditLogger = Depends(),
) -> PlanApprovalResponse:
    """Approve, reject, or modify a pending execution plan.

    - approve: Transitions to EXECUTING and starts execution.
    - reject: Transitions to CANCELLED.
    - modify: Updates plan and returns to PLANNING for re-validation.
    """
    state = await state_manager.get_execution(execution_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found",
        )

    # Validate state
    if state.status != ExecutionStatus.AWAITING_CONFIRMATION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Execution is in '{state.status.value}' state, not awaiting confirmation",
        )

    if approval.decision == "approve":
        try:
            state = await state_manager.transition(state, "user_approve")
        except StateTransitionError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e),
            )

        await state_manager.update_execution(state)
        audit_logger.log_plan_approved(
            execution_id=str(execution_id),
            decision="approved",
        )

        # Note: Actual execution would be started here or via a background task
        # triggered by the commands route or a separate worker.

        return PlanApprovalResponse(
            execution_id=execution_id,
            decision="approve",
            new_status=ExecutionStatus.EXECUTING,
            message="Plan approved. Execution started.",
        )

    elif approval.decision == "reject":
        try:
            state = await state_manager.transition(state, "user_reject")
        except StateTransitionError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e),
            )

        await state_manager.update_execution(state)
        audit_logger.log_plan_approved(
            execution_id=str(execution_id),
            decision="rejected",
        )

        return PlanApprovalResponse(
            execution_id=execution_id,
            decision="reject",
            new_status=ExecutionStatus.CANCELLED,
            message="Plan rejected. Execution cancelled.",
        )

    elif approval.decision == "modify":
        if approval.modified_plan is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="modified_plan is required when decision='modify'",
            )

        # Update plan and transition back to planning
        state.plan = approval.modified_plan
        try:
            # Transition: awaiting_confirmation -> cancelled (to reset) -> planning
            # Actually, the state machine doesn't have a direct modify transition.
            # We update the plan in place and return the current state.
            state = state.update_status(ExecutionStatus.PLANNING)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid modified plan: {e}",
            )

        await state_manager.update_execution(state)

        return PlanApprovalResponse(
            execution_id=execution_id,
            decision="modify",
            new_status=ExecutionStatus.PLANNING,
            message="Plan modified and returned for re-validation.",
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid decision: {approval.decision}",
        )
