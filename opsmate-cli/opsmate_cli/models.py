"""Pydantic models for API request/response handling."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────────


class ExecutionStatus(str, Enum):
    """Execution lifecycle states."""

    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    """Individual step states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    SKIPPED_DUE_TO_DEPENDENCY = "skipped_due_to_dependency"
    RETRYING = "retrying"


class ExecutionMode(str, Enum):
    """Execution mode values."""

    MOCK = "mock"
    LIVE = "live"
    MIXED = "mixed"


class ErrorType(str, Enum):
    """Error classification for retry/circuit-breaker decisions."""

    TRANSIENT = "transient"
    PERMANENT = "permanent"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    """Plan risk level."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# ── Command / Execution Models ────────────────────────────────────────────────


class CommandRequest(BaseModel):
    """User command submission."""

    text: str = Field(..., min_length=1, max_length=2000, description="Natural language command")
    auto_approve: bool = Field(default=False, description="Skip plan confirmation for single-step plans")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Optional client metadata")
    execution_mode_override: Literal["mock", "live", "mixed"] | None = Field(
        default=None, description="Per-command execution mode override"
    )


class CommandResponse(BaseModel):
    """Immediate acknowledgement with execution ID."""

    execution_id: UUID
    status: ExecutionStatus = ExecutionStatus.PENDING
    message: str = "Command accepted, processing started"
    execution_mode: Literal["mock", "live", "mixed"]
    stream_url: str


class ClarificationResponse(BaseModel):
    """Returned when intent confidence is too low."""

    execution_id: UUID | None = None
    confidence: float
    reason: str
    suggested_rephrasings: list[str]
    examples: list[str]


# ── Plan Models ───────────────────────────────────────────────────────────────


class PlanStep(BaseModel):
    """Individual step in an execution plan."""

    id: str = Field(..., description="Step identifier from the execution plan DAG")
    tool_name: str = Field(..., description="MCP tool name that will be called")
    server: str = Field(..., description="MCP server that handles the call")
    description: str = Field(default="", description="Human-readable step description")
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    critical: bool = Field(default=False, description="True for destructive operations")
    condition: str | None = Field(default=None, description="Conditional execution expression")
    dependencies: list[str] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    """Generated execution plan DAG."""

    steps: list[PlanStep]
    dependencies: dict[str, list[str]] = Field(default_factory=dict)
    estimated_duration_ms: int = Field(default=0)
    risk_level: RiskLevel = RiskLevel.LOW
    explanation: str = Field(default="", description="Human-readable plan explanation")


# ── Step Result Models ────────────────────────────────────────────────────────


class StepError(BaseModel):
    """Error details for a failed step."""

    classification: ErrorType = ErrorType.UNKNOWN
    message: str
    retryable: bool = False
    attempt_count: int = 1


class StepResult(BaseModel):
    """Individual step execution result."""

    step_id: str
    tool_name: str
    server: str
    status: StepStatus = StepStatus.PENDING
    output: dict[str, Any] | None = None
    error: StepError | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float | None = None
    attempt_count: int = 1


# ── Execution Context ─────────────────────────────────────────────────────────


class ExecutionContext(BaseModel):
    """Shared execution context."""

    variables: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    secrets_redacted: bool = True


# ── SSE Event Models ──────────────────────────────────────────────────────────


class StepStartedEvent(BaseModel):
    """Emitted when a step begins execution."""

    step_id: str
    tool_name: str
    server: str
    started_at: str  # ISO8601


class StepCompletedEvent(BaseModel):
    """Emitted when a step finishes successfully."""

    step_id: str
    tool_name: str
    server: str
    status: str = "completed"
    output_preview: str
    started_at: str
    completed_at: str
    duration_ms: float


class StepFailedEvent(BaseModel):
    """Emitted when a step fails."""

    step_id: str
    tool_name: str
    server: str
    status: str = "failed"
    error_classification: ErrorType
    error_message: str
    retryable: bool
    attempt_count: int
    started_at: str
    completed_at: str | None = None


class EscalationEvent(BaseModel):
    """Emitted when human intervention is needed."""

    step_id: str
    reason: str
    options: list[str]
    timeout_seconds: int = 300
    impact: str


class ExecutionCompletedEvent(BaseModel):
    """Emitted when all steps are finished."""

    execution_id: UUID
    status: ExecutionStatus = ExecutionStatus.COMPLETED
    summary: str
    result_preview: dict[str, Any]
    total_duration_ms: float
    completed_at: str


class ExecutionFailedEvent(BaseModel):
    """Emitted when execution fails irrecoverably."""

    execution_id: UUID
    status: ExecutionStatus = ExecutionStatus.FAILED
    failure_reason: str
    failed_step_id: str | None = None
    total_duration_ms: float
    completed_at: str


class ExecutionCancelledEvent(BaseModel):
    """Emitted when execution is cancelled."""

    execution_id: UUID
    status: ExecutionStatus = ExecutionStatus.CANCELLED
    reason: str
    cancelled_at: str


class PlanAwaitingConfirmationEvent(BaseModel):
    """Emitted when a multi-step plan is ready for approval."""

    execution_id: UUID
    plan: ExecutionPlan
    risk_level: RiskLevel


# ── Execution History Models ──────────────────────────────────────────────────


class ExecutionSummary(BaseModel):
    """Lightweight execution record for listing."""

    execution_id: UUID
    status: ExecutionStatus
    command_text: str
    execution_mode: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    total_duration_ms: float | None = None
    step_count: int = 0
    failed_steps: int = 0


class ExecutionListResponse(BaseModel):
    """Paginated list of executions."""

    items: list[ExecutionSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


class AuditLogEntry(BaseModel):
    """Single audit log entry."""

    action: str
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime
    user_id: str | None = None


class ExecutionDetailResponse(BaseModel):
    """Full execution state."""

    execution_id: UUID
    status: ExecutionStatus
    command_text: str
    execution_mode: str
    plan: ExecutionPlan | None = None
    results: dict[str, StepResult] = Field(default_factory=dict)
    context: ExecutionContext = Field(default_factory=ExecutionContext)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    planning_duration_ms: float | None = None
    total_duration_ms: float | None = None
    audit_log: list[AuditLogEntry] = Field(default_factory=list)


# ── Plan Approval Models ──────────────────────────────────────────────────────


class PlanApprovalRequest(BaseModel):
    """User decision on a pending execution plan."""

    decision: Literal["approve", "reject", "modify"]
    modified_plan: ExecutionPlan | None = None
    reason: str | None = None


class PlanApprovalResponse(BaseModel):
    """Result of plan approval action."""

    execution_id: UUID
    decision: str
    new_status: ExecutionStatus
    message: str


# ── Health Models ─────────────────────────────────────────────────────────────


class HealthCheckDetail(BaseModel):
    """Individual health check detail."""

    status: Literal["ok", "warning", "critical"]
    response_time_ms: float
    detail: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    uptime_seconds: float
    timestamp: datetime
    checks: dict[str, HealthCheckDetail] = Field(default_factory=dict)


# ── Example / Demo Models ─────────────────────────────────────────────────────


class DemoCommand(BaseModel):
    """Built-in demo command."""

    title: str
    description: str
    command: str
    expected_plan_template: str
    category: str


class ExamplesResponse(BaseModel):
    """Demo commands response."""

    examples: list[DemoCommand]


# ── Error Models ──────────────────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    """Standard error response body."""

    error: str
    detail: str | None = None
    execution_id: UUID | None = None
    request_id: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ValidationErrorDetail(BaseModel):
    """Single validation error detail."""

    loc: list[str]
    msg: str
    type: str


class ValidationErrorResponse(BaseModel):
    """Pydantic validation error response."""

    error: str = "Validation error"
    detail: list[ValidationErrorDetail]
    request_id: str
    timestamp: datetime
