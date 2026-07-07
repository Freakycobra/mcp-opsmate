"""Core enums and constants for mcp-opsmate."""

from __future__ import annotations

from enum import Enum


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


class ErrorType(str, Enum):
    """Error classification for retry and circuit-breaker decisions."""

    TRANSIENT = "transient"
    PERMANENT = "permanent"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


class ErrorClassification:
    """Structured error classification result."""

    def __init__(
        self,
        error_type: ErrorType,
        retryable: bool,
        increment_circuit: bool,
        escalate: bool = False,
    ) -> None:
        self.error_type = error_type
        self.retryable = retryable
        self.increment_circuit = increment_circuit
        self.escalate = escalate

    def __repr__(self) -> str:
        return (
            f"ErrorClassification(type={self.error_type.value}, "
            f"retryable={self.retryable}, circuit={self.increment_circuit})"
        )


class IntentType(str, Enum):
    """Types of user intent."""

    QUERY = "query"
    ACTION = "action"
    ANALYZE = "analyze"
    NOTIFY = "notify"
    CORRELATE = "correlate"
    REMEDIATE = "remediate"


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ExecutionMode(str, Enum):
    """Execution mode values."""

    MOCK = "mock"
    LIVE = "live"
    MIXED = "mixed"


class RiskLevel(str, Enum):
    """Risk levels for execution plans."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class StreamEventType(str, Enum):
    """SSE event types."""

    EXECUTION_CREATED = "execution.created"
    PLAN_GENERATED = "plan.generated"
    PLAN_AWAITING_CONFIRMATION = "plan.awaiting_confirmation"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    STEP_SKIPPED = "step.skipped"
    ESCALATION_REQUIRED = "escalation.required"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
    EXECUTION_CANCELLED = "execution.cancelled"
    HEARTBEAT = "heartbeat"


# ---------------------------------------------------------------------------
# Default constants
# ---------------------------------------------------------------------------

MAX_RETRIES: int = 3
"""Maximum retry attempts for transient errors."""

CIRCUIT_BREAKER_THRESHOLD: int = 5
"""Consecutive failures before opening circuit breaker."""

CIRCUIT_BREAKER_TIMEOUT: int = 30
"""Seconds to wait before half-open probe."""

CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS: int = 1
"""Maximum calls allowed in half-open state."""

HUMAN_ESCALATION_TIMEOUT: int = 300
"""Seconds before auto-abort on human escalation timeout."""

INTENT_CLASSIFICATION_CONFIDENCE_THRESHOLD: float = 0.70
"""Minimum confidence for intent classification."""

PLAN_CONFIRMATION_TIMEOUT: int = 300
"""Seconds before auto-cancel of awaiting_confirmation."""

DEFAULT_RETRY_BACKOFF_BASE: float = 1.0
"""Base seconds for exponential backoff."""

MAX_CONCURRENT_STEPS: int = 10
"""Maximum parallel steps in a single execution."""

SSE_HEARTBEAT_INTERVAL: int = 15
"""Seconds between SSE heartbeat events."""

MCP_HEALTH_CHECK_INTERVAL: int = 30
"""Seconds between MCP server health checks."""

MCP_RECONNECT_MAX_ATTEMPTS: int = 5
"""Maximum reconnection attempts to an MCP server."""

MCP_TOOL_CALL_TIMEOUT: int = 30
"""Seconds before MCP tool call timeout."""

EXECUTION_RETENTION_DAYS: int = 30
"""Days to retain execution history."""

DEFAULT_TEMPERATURE: float = 0.2
"""LLM temperature for deterministic planning."""

DEFAULT_MAX_TOKENS: int = 4096
"""Maximum LLM tokens for planning."""

PLANNING_TIMEOUT_MS: int = 5000
"""Milliseconds timeout for plan generation."""
