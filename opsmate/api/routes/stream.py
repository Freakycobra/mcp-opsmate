"""SSE stream route for mcp-opsmate.

GET /stream/{execution_id} -- Server-Sent Events for real-time execution updates.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from opsmate.core.constants import SSE_HEARTBEAT_INTERVAL, ExecutionStatus
from opsmate.services.state import StateManager

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(tags=["Stream"])

# SSE event queues per execution (shared with commands.py)
# This is populated by commands.py's _emit_event function
_sse_queues: dict[UUID, asyncio.Queue[dict[str, Any]]] = {}


async def _get_or_create_queue(execution_id: UUID) -> asyncio.Queue[dict[str, Any]]:
    """Get or create an SSE event queue for an execution."""
    if execution_id not in _sse_queues:
        _sse_queues[execution_id] = asyncio.Queue()
    return _sse_queues[execution_id]


async def _sse_event_generator(
    execution_id: UUID,
    state_manager: StateManager,
) -> AsyncGenerator[str, None]:
    """Generate SSE event stream for an execution.

    Yields formatted SSE events: event type, data, and optional id.
    Sends heartbeats every 15 seconds to keep connection alive.
    """
    queue: asyncio.Queue[dict[str, Any]] = await _get_or_create_queue(execution_id)
    event_id: int = 0

    # Send initial execution state
    state = await state_manager.get_execution(execution_id)
    if state:
        yield f"event: execution.created\ndata: {json.dumps({\"execution_id\": str(execution_id), \"status\": state.status.value, \"message\": \"Stream connected\"})}\nid: {event_id}\n\n"
        event_id += 1

    last_heartbeat: float = asyncio.get_event_loop().time()

    try:
        while True:
            # Check for heartbeat interval
            now: float = asyncio.get_event_loop().time()
            if now - last_heartbeat >= SSE_HEARTBEAT_INTERVAL:
                heartbeat_data: dict[str, str] = {
                    "timestamp": datetime.utcnow().isoformat(),
                }
                yield f"event: heartbeat\ndata: {json.dumps(heartbeat_data)}\nid: {event_id}\n\n"
                event_id += 1
                last_heartbeat = now

            # Try to get event with timeout
            try:
                event: dict[str, Any] = await asyncio.wait_for(
                    queue.get(), timeout=1.0
                )
                event_type: str = event.get("event", "message")
                event_data: dict[str, Any] = event.get("data", {})

                yield f"event: {event_type}\ndata: {json.dumps(event_data)}\nid: {event_id}\n\n"
                event_id += 1

                # Check if execution is terminal - close stream
                if event_type in ("execution.completed", "execution.failed", "execution.cancelled"):
                    logger.info("Execution %s terminal event received, closing stream", execution_id)
                    break

            except asyncio.TimeoutError:
                # No event received, loop continues (heartbeat check)
                continue

    except asyncio.CancelledError:
        logger.debug("SSE stream cancelled for execution %s", execution_id)
        raise
    finally:
        # Clean up queue reference
        _sse_queues.pop(execution_id, None)


@router.get("/stream/{execution_id}")
async def stream_execution(
    execution_id: UUID,
    request: Request,
    state_manager: StateManager = Depends(),
) -> StreamingResponse:
    """SSE stream for real-time execution updates.

    Events: plan.generated, step.started, step.completed, step.failed,
    escalation.required, execution.completed, execution.failed,
    execution.cancelled, heartbeat
    """
    # Verify execution exists
    state = await state_manager.get_execution(execution_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found",
        )

    return StreamingResponse(
        _sse_event_generator(execution_id, state_manager),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
