# mcp-opsmate — Technical Specification

**Version:** 1.0
**Author:** Staff Engineer (AI)
**Date:** 2025-06-01
**Status:** Draft
**Based on:** `requirements.md` v1.0 + `architecture.md` v1.0

---

## Table of Contents

1. [API Contract](#1-api-contract)
2. [Database Schema](#2-database-schema)
3. [Pydantic Models](#3-pydantic-models)
4. [MCP Server Interface Definitions](#4-mcp-server-interface-definitions)
5. [Configuration Schema](#5-configuration-schema)
6. [Package Structure & Dependencies](#6-package-structure--dependencies)
7. [Docker Compose Specification](#7-docker-compose-specification)
8. [Additional Technical Decisions](#8-additional-technical-decisions)
9. [Testing Strategy Details](#9-testing-strategy-details)
10. [Implementation Order & Estimates](#10-implementation-order--estimates)

---

## 1. API Contract

### 1.1 Authentication

The API uses a two-tier authentication scheme:

| Tier | Header | Scope | Validation |
|---|---|---|---|
| **Standard API Key** | `X-API-Key: <key>` | All endpoints except `/health` | Constant-time string comparison against `API_KEY` env var |
| **Admin Bearer Token** | `Authorization: Bearer <token>` | `/admin/*` endpoints only | JWT or constant-time comparison against `ADMIN_API_TOKEN` env var; regular API key is rejected with 403 |

**Unauthenticated responses:**
- Missing auth on protected endpoint: `401 Unauthorized`
- Valid API key on admin endpoint: `403 Forbidden` (requires admin token)
- Invalid/expired admin token: `401 Unauthorized`

### 1.2 Base URL & Content Type

- Base: `http://localhost:8000`
- All requests/responses: `Content-Type: application/json` unless otherwise specified
- SSE streams: `Content-Type: text/event-stream`
- Prometheus metrics: `Content-Type: text/plain; version=0.0.4`

### 1.3 Endpoint Specifications

#### `POST /commands` — Submit New Command

Receives a natural language command, begins intent classification and plan generation.

| Attribute | Value |
|---|---|
| **Path** | `/commands` |
| **Method** | `POST` |
| **Auth** | `X-API-Key` required |
| **Req. IDs** | FR-01, FR-02, FR-03, FR-09, FR-29, FR-33 |

**Request Body:**

```python
class CommandRequest(BaseModel):
    """User command submission."""
    text: str = Field(..., min_length=1, max_length=2000, description="Natural language command")
    auto_approve: bool = Field(default=False, description="Skip plan confirmation for single-step plans")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Optional client metadata")
    execution_mode_override: Literal["mock", "live", "mixed"] | None = Field(
        default=None, description="Per-command execution mode override"
    )
```

**Response: `202 Accepted`**

```python
class CommandResponse(BaseModel):
    """Immediate acknowledgement with execution ID."""
    execution_id: UUID
    status: ExecutionStatus = ExecutionStatus.PENDING
    message: str = "Command accepted, processing started"
    execution_mode: Literal["mock", "live", "mixed"]
    stream_url: str  # URL to connect for SSE: /stream/{execution_id}
```

**Other Status Codes:**

| Code | Trigger | Response Body |
|---|---|---|
| `400` | Validation error (empty command, too long) | `ValidationErrorResponse` |
| `401` | Missing/invalid API key | `ErrorResponse` |
| `422` | Low intent confidence (< 70%); clarification required | `ClarificationResponse` |
| `503` | Required MCP servers unavailable and no mock fallback | `ErrorResponse` |

**Clarification Response (`422`):**

```python
class ClarificationResponse(BaseModel):
    """Returned when intent confidence is too low."""
    execution_id: UUID | None
    confidence: float
    reason: str
    suggested_rephrasings: list[str]
    examples: list[str]
```

---

#### `GET /executions` — List Executions

Paginated list of executions with filtering support.

| Attribute | Value |
|---|---|
| **Path** | `/executions` |
| **Method** | `GET` |
| **Auth** | `X-API-Key` required |
| **Req. IDs** | FR-23 |

**Query Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `page` | `int` | `1` | Page number (1-indexed) |
| `page_size` | `int` | `20` | Items per page (max 100) |
| `status` | `ExecutionStatus` | `None` | Filter by status (pending/planning/awaiting_confirmation/executing/completed/failed/cancelled/paused) |
| `mode` | `str` | `None` | Filter by execution mode (mock/live/mixed) |
| `from_date` | `datetime` | `None` | Start of date range (ISO 8601) |
| `to_date` | `datetime` | `None` | End of date range (ISO 8601) |
| `command_q` | `str` | `None` | Fuzzy search on command text |
| `sort` | `str` | `-created_at` | Sort field, prefix `-` for descending |

**Response: `200 OK`**

```python
class ExecutionListResponse(BaseModel):
    """Paginated list of executions."""
    items: list[ExecutionSummary]
    total: int
    page: int
    page_size: int
    total_pages: int

class ExecutionSummary(BaseModel):
    """Lightweight execution record for listing."""
    execution_id: UUID
    status: ExecutionStatus
    command_text: str
    execution_mode: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    total_duration_ms: float | None
    step_count: int
    failed_steps: int
```

---

#### `GET /executions/{execution_id}` — Get Execution Detail

Full execution state including plan, step results, and context.

| Attribute | Value |
|---|---|
| **Path** | `/executions/{execution_id}` |
| **Method** | `GET` |
| **Auth** | `X-API-Key` required |
| **Req. IDs** | FR-23 |

**Path Parameters:**

| Param | Type | Description |
|---|---|---|
| `execution_id` | `UUID` | Execution identifier |

**Response: `200 OK`**

```python
class ExecutionDetailResponse(BaseModel):
    """Full execution state."""
    execution_id: UUID
    status: ExecutionStatus
    command_text: str
    execution_mode: str
    plan: ExecutionPlan | None
    results: dict[str, StepResult]
    context: ExecutionContext
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    planning_duration_ms: float | None
    total_duration_ms: float | None
    audit_log: list[AuditLogEntry]
```

**Status Codes:**

| Code | Trigger |
|---|---|
| `200` | Success |
| `401` | Invalid API key |
| `404` | Execution not found |

---

#### `POST /executions/{execution_id}/approve` — Approve a Pending Plan

User approval for an execution plan awaiting confirmation.

| Attribute | Value |
|---|---|
| **Path** | `/executions/{execution_id}/approve` |
| **Method** | `POST` |
| **Auth** | `X-API-Key` required |
| **Req. IDs** | FR-09, FR-10 |

**Path Parameters:**

| Param | Type | Description |
|---|---|---|
| `execution_id` | `UUID` | Execution identifier |

**Request Body:**

```python
class PlanApprovalRequest(BaseModel):
    """User decision on a pending execution plan."""
    decision: Literal["approve", "reject", "modify"]
    modified_plan: ExecutionPlan | None = Field(
        default=None,
        description="If decision='modify', the modified plan. Must preserve DAG validity."
    )
    reason: str | None = Field(default=None, description="Reason for rejection/modification")
```

**Response: `200 OK` (approve)**

```python
class PlanApprovalResponse(BaseModel):
    """Result of plan approval action."""
    execution_id: UUID
    decision: str
    new_status: ExecutionStatus
    message: str
```

**Status Codes:**

| Code | Trigger |
|---|---|
| `200` | Approval/rejection processed successfully |
| `400` | Invalid decision (e.g., modify without modified_plan) |
| `401` | Invalid API key |
| `404` | Execution not found |
| `409` | Execution not in AWAITING_CONFIRMATION state |

**Response for `decision=reject`:** Status transitions to `CANCELLED`.
**Response for `decision=modify`:** Plan is updated, execution returns to `PLANNING` for re-validation.

---

#### `GET /stream/{execution_id}` — SSE Stream for Real-Time Updates

Server-Sent Events stream for live execution updates.

| Attribute | Value |
|---|---|
| **Path** | `/stream/{execution_id}` |
| **Method** | `GET` |
| **Auth** | `X-API-Key` via query param `?api_key=<key>` (SSE headers limited) |
| **Content-Type** | `text/event-stream` |
| **Req. IDs** | FR-36, FR-38, FR-39 |

**Path Parameters:**

| Param | Type | Description |
|---|---|---|
| `execution_id` | `UUID` | Execution to stream |

**SSE Event Types & Payloads:**

| Event Type (`event:`) | When Sent | Payload Schema |
|---|---|---|
| `execution.created` | Initial connection | `{"execution_id": "uuid", "status": "pending", "message": "..."}` |
| `plan.generated` | Plan generation complete | `ExecutionPlan` JSON |
| `plan.awaiting_confirmation` | Multi-step plan ready for approval | `{"execution_id": "uuid", "plan": {...}, "risk_level": "LOW\|MEDIUM\|HIGH"}` |
| `step.started` | A step begins execution | `{"step_id": "str", "tool_name": "str", "server": "str", "started_at": "ISO8601"}` |
| `step.completed` | A step finishes successfully | `StepCompletedEvent` |
| `step.failed` | A step fails (after retries) | `StepFailedEvent` |
| `step.skipped` | A step skipped due to condition | `{"step_id": "str", "reason": "str"}` |
| `escalation.required` | Human-in-the-loop triggered | `EscalationEvent` |
| `execution.completed` | All steps finished | `ExecutionCompletedEvent` |
| `execution.failed` | Execution failed irrecoverably | `ExecutionFailedEvent` |
| `execution.cancelled` | User cancelled or timeout | `ExecutionCancelledEvent` |
| `heartbeat` | Every 15s to keep connection alive | `{"timestamp": "ISO8601"}` |

**SSE Payload Schemas:**

```python
class StepCompletedEvent(BaseModel):
    step_id: str
    tool_name: str
    server: str
    status: str = "completed"
    output_preview: str  # Truncated output for display
    started_at: datetime
    completed_at: datetime
    duration_ms: float

class StepFailedEvent(BaseModel):
    step_id: str
    tool_name: str
    server: str
    status: str = "failed"
    error_classification: ErrorType
    error_message: str
    retryable: bool
    attempt_count: int
    started_at: datetime
    completed_at: datetime | None

class EscalationEvent(BaseModel):
    step_id: str
    reason: str
    options: list[str]  # ["retry", "skip", "abort"]
    timeout_seconds: int = 300
    impact: str  # Description of downstream impact

class ExecutionCompletedEvent(BaseModel):
    execution_id: UUID
    status: ExecutionStatus = ExecutionStatus.COMPLETED
    summary: str
    result_preview: dict[str, Any]
    total_duration_ms: float
    completed_at: datetime

class ExecutionFailedEvent(BaseModel):
    execution_id: UUID
    status: ExecutionStatus = ExecutionStatus.FAILED
    failure_reason: str
    failed_step_id: str | None
    total_duration_ms: float
    completed_at: datetime

class ExecutionCancelledEvent(BaseModel):
    execution_id: UUID
    status: ExecutionStatus = ExecutionStatus.CANCELLED
    reason: str
    cancelled_at: datetime
```

**SSE Format:**

```text
event: step.started
data: {"step_id": "step-1", "tool_name": "describe_pods", ...}

id: <event-sequence-number>
event: step.completed
data: {"step_id": "step-1", ...}
```

---

#### `GET /health` — Health Check

| Attribute | Value |
|---|---|
| **Path** | `/health` |
| **Method** | `GET` |
| **Auth** | None required |
| **Req. IDs** | FR-27, NFR-06 |

**Response: `200 OK` (healthy)** / **`503 Service Unavailable` (degraded)**

```python
class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    uptime_seconds: float
    timestamp: datetime
    checks: dict[str, HealthCheckDetail]

class HealthCheckDetail(BaseModel):
    status: Literal["ok", "warning", "critical"]
    response_time_ms: float
    detail: str | None = None

# Example checks dict:
# {
#   "postgresql": {"status": "ok", "response_time_ms": 5.2},
#   "redis": {"status": "ok", "response_time_ms": 2.1},
#   "mcp-tavily-search": {"status": "ok", "response_time_ms": 150},
#   "mcp-github": {"status": "ok", "response_time_ms": 80},
#   ...
# }
```

**Status code logic:**
- `200`: PostgreSQL + Redis OK, all critical MCP servers connected
- `503`: PostgreSQL or Redis down, OR any critical MCP server disconnected > 60s

---

#### `GET /metrics` — Prometheus Metrics

| Attribute | Value |
|---|---|
| **Path** | `/metrics` |
| **Method** | `GET` |
| **Auth** | None required (Prometheus scraping) |
| **Content-Type** | `text/plain; version=0.0.4` |
| **Req. IDs** | NFR-19 |

**Exposed Metrics:**

| Metric Name | Type | Labels | Description |
|---|---|---|---|
| `opsmate_requests_total` | Counter | `method`, `path`, `status_code` | Total HTTP requests |
| `opsmate_request_duration_seconds` | Histogram | `method`, `path` | Request latency distribution |
| `opsmate_executions_total` | Counter | `status`, `mode` | Total executions by final status |
| `opsmate_executions_active` | Gauge | `mode` | Currently executing plans |
| `opsmate_execution_duration_seconds` | Histogram | `mode`, `plan_template` | Execution duration |
| `opsmate_steps_total` | Counter | `status`, `tool_name`, `server` | Total steps by status |
| `opsmate_step_duration_seconds` | Histogram | `tool_name`, `server` | Step execution duration |
| `opsmate_mcp_server_connected` | Gauge | `server_name` | 1 if connected, 0 if disconnected |
| `opsmate_mcp_circuit_breaker_state` | Gauge | `server_name` | 0=closed, 1=half-open, 2=open |
| `opsmate_retries_total` | Counter | `tool_name`, `server`, `error_type` | Retry attempts |
| `opsmate_errors_total` | Counter | `type`, `server`, `tool_name` | Total errors |

---

#### `GET /admin/mode` — Get Current Execution Mode

| Attribute | Value |
|---|---|
| **Path** | `/admin/mode` |
| **Method** | `GET` |
| **Auth** | `Authorization: Bearer <admin_token>` |
| **Req. IDs** | FR-29, FR-32, FR-33 |

**Response: `200 OK`**

```python
class ModeConfigurationResponse(BaseModel):
    """Current execution mode configuration."""
    global_mode: Literal["mock", "live", "mixed"]
    effective_mode: Literal["mock", "live", "mixed"]
    server_modes: dict[str, Literal["mock", "live", "local"]]
    can_switch_at_runtime: bool = True
    active_executions: int  # Number of in-flight executions
    last_changed_at: datetime | None
    last_changed_by: str | None
```

---

#### `POST /admin/mode` — Switch Execution Mode

| Attribute | Value |
|---|---|
| **Path** | `/admin/mode` |
| **Method** | `POST` |
| **Auth** | `Authorization: Bearer <admin_token>` |
| **Req. IDs** | FR-32, FR-44 |

**Request Body:**

```python
class ModeSwitchRequest(BaseModel):
    """Request to change execution mode."""
    global_mode: Literal["mock", "live", "mixed"]
    server_overrides: dict[str, Literal["mock", "live", "local"]] = Field(
        default_factory=dict,
        description="Per-server mode overrides. Only applied when global_mode='mixed'."
    )
    reason: str = Field(..., min_length=1, description="Reason for mode change (audited)")
    force: bool = Field(default=False, description="Force switch even with active executions")
```

**Validation Rules:**
- Mode change rejected if `active_executions > 0` and `force=False`
- In-flight executions continue in their original mode
- Change logged to audit trail with admin identity
- Switch to `live` from `mock` requires explicit acknowledgment

**Response: `200 OK`**

```python
class ModeSwitchResponse(BaseModel):
    """Result of mode switch."""
    previous_mode: str
    new_mode: str
    applied_at: datetime
    active_executions_unchanged: int
    message: str
```

---

#### `GET /admin/tools` — List Available MCP Tools

| Attribute | Value |
|---|---|
| **Path** | `/admin/tools` |
| **Method** | `GET` |
| **Auth** | `Authorization: Bearer <admin_token>` |
| **Req. IDs** | FR-11, FR-12, FR-42, FR-43 |

**Response: `200 OK`**

```python
class ToolRegistryResponse(BaseModel):
    """Snapshot of the tool registry."""
    last_refreshed_at: datetime
    server_count: int
    total_tools: int
    servers: list[ServerToolsInfo]

class ServerToolsInfo(BaseModel):
    server_name: str
    transport: str
    connected: bool
    mode: Literal["mock", "live", "local"]
    tool_count: int
    tools: list[ToolInfo]

class ToolInfo(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema
    output_schema: dict[str, Any] | None  # JSON Schema (if known)
    server: str
    destructive: bool = False  # True for restart, delete, modify operations
```

---

#### `POST /admin/tools/refresh` — Refresh Tool Registry

Force re-discovery of all MCP tools. Useful after MCP server restart or configuration change.

| Attribute | Value |
|---|---|
| **Path** | `/admin/tools/refresh` |
| **Method** | `POST` |
| **Auth** | `Authorization: Bearer <admin_token>` |
| **Req. IDs** | FR-11, FR-44 |

**Response: `200 OK`**

```python
class ToolRefreshResponse(BaseModel):
    refreshed_at: datetime
    servers_discovered: int
    tools_discovered: int
    servers: list[ServerRefreshResult]

class ServerRefreshResult(BaseModel):
    server_name: str
    status: Literal["ok", "failed", "timeout"]
    tools_found: int
    error: str | None
```

---

#### `POST /admin/executions/{execution_id}/escalation` — Resolve Escalation

Respond to a human-in-the-loop escalation prompt.

| Attribute | Value |
|---|---|
| **Path** | `/admin/executions/{execution_id}/escalation` |
| **Method** | `POST` |
| **Auth** | `X-API-Key` required |
| **Req. IDs** | FR-19 |

**Request Body:**

```python
class EscalationResolutionRequest(BaseModel):
    """User response to an escalation prompt."""
    decision: Literal["continue", "abort", "retry", "skip_step"]
    modified_step_params: dict[str, Any] | None = None
    reason: str | None = None
```

**Response: `200 OK`**

Returns `ExecutionDetailResponse` with updated status.

---

#### `GET /examples` — Demo Commands

Returns built-in demo commands for zero-config onboarding.

| Attribute | Value |
|---|---|
| **Path** | `/examples` |
| **Method** | `GET` |
| **Auth** | None required |
| **Req. IDs** | US-4 |

**Response: `200 OK`**

```python
class ExamplesResponse(BaseModel):
    examples: list[DemoCommand]

class DemoCommand(BaseModel):
    title: str
    description: str
    command: str
    expected_plan_template: str  # e.g., "health-check-and-remediate"
    category: str  # "health", "incident", "analysis", "correlation"
```

---

### 1.4 WebSocket Message Types

The WebSocket endpoint `/ws/executions` provides bidirectional real-time communication primarily for the Web UI DAG visualization.

**Connection:** `ws://localhost:8000/w/executions?api_key=<key>`

**Client → Server Messages:**

| Message Type | Payload | Description |
|---|---|---|
| `subscribe` | `{"execution_id": "uuid"}` | Subscribe to execution updates |
| `unsubscribe` | `{"execution_id": "uuid"}` | Unsubscribe from execution |
| `heartbeat` | `{}` | Keep connection alive |

**Server → Client Messages:**

| Message Type | Payload | Description |
|---|---|---|
| `execution.update` | `ExecutionDetailResponse` | Full state update |
| `step.update` | `StepUpdatePayload` | Incremental step status change |
| `dag.update` | `DAGUpdatePayload` | DAG structure change (for ReactFlow) |
| `error` | `WebSocketErrorPayload` | Server-side error |

```python
class StepUpdatePayload(BaseModel):
    execution_id: UUID
    step_id: str
    status: StepStatus
    output: dict[str, Any] | None = None
    error: StepError | None = None
    progress_percent: float | None = None  # For long-running steps

class DAGUpdatePayload(BaseModel):
    execution_id: UUID
    nodes: list[DAGNode]
    edges: list[DAGEdge]

class DAGNode(BaseModel):
    id: str  # step_id
    type: str  # "tool", "decision", "human"
    position: dict[str, float]  # {"x": 100, "y": 200}
    data: dict[str, Any]  # {tool_name, status, label, ...}

class DAGEdge(BaseModel):
    id: str
    source: str  # from node id
    target: str  # to node id
    animated: bool = False  # True if dependency is active

class WebSocketErrorPayload(BaseModel):
    code: str
    message: str
    execution_id: UUID | None = None
```

---

### 1.5 Shared Error Response Models

```python
class ErrorResponse(BaseModel):
    """Standard error response body."""
    error: str
    detail: str | None = None
    execution_id: UUID | None = None
    request_id: str  # For correlation with server logs
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ValidationErrorResponse(BaseModel):
    """Pydantic validation error response."""
    error: str = "Validation error"
    detail: list[ValidationErrorDetail]
    request_id: str
    timestamp: datetime

class ValidationErrorDetail(BaseModel):
    loc: list[str]  # ["body", "text"] or ["query", "page"]
    msg: str
    type: str
```



---

## 2. Database Schema

### 2.1 Technology Stack

| Layer | Technology | Version | Rationale |
|---|---|---|---|
| ORM | SQLAlchemy | 2.0+ | Native async support; `asyncpg` dialect; type hints |
| Async Driver | asyncpg | 0.29+ | Best-in-class async PostgreSQL performance |
| Migrations | Alembic | 1.13+ | SQLAlchemy-native; async support |
| JSON Column | PostgreSQL JSONB | 16+ | Indexed JSON; schema flexibility for plans/results |

### 2.2 SQLAlchemy Model Definitions

All models use SQLAlchemy 2.0 declarative base with `Mapped` type annotations and `mapped_column`.

```python
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON, DateTime, Float, ForeignKey, Integer, String, Text, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy models."""
    pass


class ExecutionStatus(str, Enum):
    """Execution lifecycle states. See architecture.md Section 4."""
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
```

#### Table: `executions`

Central execution state table. One row per user command.

```python
class Execution(Base):
    """Persisted execution state. See architecture.md Section 2.5."""

    __tablename__ = "executions"

    # Primary key
    execution_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        comment="Unique execution identifier"
    )

    # State
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        default=ExecutionStatus.PENDING.value,
        comment="Current execution status (from ExecutionStatus enum)"
    )

    # Input
    command_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Original natural language command"
    )

    # Execution plan (stored as JSONB for schema flexibility)
    plan: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Serialized ExecutionPlan as JSONB"
    )

    # Step results (aggregated, denormalized for fast reads)
    results: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Dict of step_id -> serialized StepResult"
    )

    # Execution context
    context: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Serialized ExecutionContext"
    )

    # Metadata
    execution_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ExecutionMode.MOCK.value,
        comment="mock | live | mixed"
    )

    # Timing
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        index=True,
        comment="Execution creation timestamp (UTC)"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="Last state update timestamp (UTC)"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Execution completion timestamp (UTC)"
    )

    # Performance metrics
    planning_duration_ms: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Intent classification + plan generation duration"
    )
    total_duration_ms: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Total wall-clock execution duration"
    )

    # Relationships
    step_results: Mapped[list["StepResult"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="StepResult.started_at",
        lazy="selectin",
        comment="Individual step results (normalized table)"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="AuditLog.timestamp",
        lazy="selectin",
        comment="Audit trail entries for this execution"
    )

    # Indexes
    __table_args__ = (
        Index("ix_executions_status_created", "status", "created_at"),
        Index("ix_executions_mode_created", "execution_mode", "created_at"),
        Index("ix_executions_command_gin", "command_text"),  # PostgreSQL trigram for search
    )
```

#### Table: `step_results`

Normalized step results for efficient querying and reporting.

```python
class StepResult(Base):
    """Individual step execution result. One row per step per execution."""

    __tablename__ = "step_results"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4
    )

    # Foreign key to execution
    execution_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("executions.execution_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Step identity
    step_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Step identifier from the execution plan DAG"
    )
    tool_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="MCP tool name that was called"
    )
    server_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="MCP server that handled the call"
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="Step status (from StepStatus enum)"
    )

    # Output
    output: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Tool call output (JSON-serialized)"
    )

    # Error details
    error: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Serialized StepError if step failed"
    )

    # Retry tracking
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Number of execution attempts (1 = first try)"
    )

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Step start timestamp"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Step completion timestamp"
    )

    # Relationship
    execution: Mapped["Execution"] = relationship(back_populates="step_results")

    # Constraints
    __table_args__ = (
        UniqueConstraint("execution_id", "step_id", name="uq_step_per_execution"),
        Index("ix_step_results_execution_status", "execution_id", "status"),
        Index("ix_step_results_server_tool", "server_name", "tool_name"),
    )
```

#### Table: `audit_logs`

Immutable audit trail. Append-only.

```python
class AuditLog(Base):
    """Structured audit log entry. Append-only, never updated or deleted."""

    __tablename__ = "audit_logs"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4
    )

    # Foreign key
    execution_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("executions.execution_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="NULL for system-level events without an execution"
    )

    # Action details
    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="Action type: command_received, plan_generated, step_started, step_completed, step_failed, execution_completed, execution_failed, mode_switched, plan_approved, plan_rejected, escalation_triggered, escalation_resolved"
    )
    details: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Action-specific details (sanitized, no secrets)"
    )

    # Identity
    user_id: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment="User identifier if available (API key hash, etc.)"
    )

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        index=True,
        comment="Event timestamp (UTC)"
    )

    # Relationship
    execution: Mapped["Execution | None"] = relationship(back_populates="audit_logs")

    # Indexes
    __table_args__ = (
        Index("ix_audit_logs_execution_action", "execution_id", "action"),
        Index("ix_audit_logs_timestamp", "timestamp"),
    )
```

#### Table: `mcp_server_states`

Tracks MCP server connection health and circuit breaker state.

```python
class MCPServerState(Base):
    """MCP server connection and circuit breaker state."""

    __tablename__ = "mcp_server_states"

    # Primary key
    server_name: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="MCP server identifier (e.g., 'github', 'aws-ecs')"
    )

    # Connection state
    connected: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        comment="Whether the server is currently connected"
    )
    transport: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="stdio | sse"
    )
    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="mock",
        comment="mock | live | local"
    )

    # Circuit breaker
    circuit_state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="closed",
        comment="closed | half_open | open"
    )
    failure_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Consecutive failure count"
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last failure"
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last successful call"
    )

    # Tool cache
    tools_cached: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="Cached tool schemas from this server"
    )
    tools_cached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When tools were last discovered"
    )

    # Metadata
    last_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    last_disconnected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )
```

### 2.3 Entity Relationship Diagram

```text
executions ||--o{ step_results : "contains"
executions ||--o{ audit_logs : "generates"
executions ||--|| mcp_server_states : "uses (indirect)"

executions:
  PK execution_id UUID
  status VARCHAR(32) [index]
  command_text TEXT
  plan JSONB
  results JSONB
  context JSONB
  execution_mode VARCHAR(16)
  created_at TIMESTAMPTZ [index]
  updated_at TIMESTAMPTZ
  completed_at TIMESTAMPTZ
  planning_duration_ms FLOAT
  total_duration_ms FLOAT

step_results:
  PK id UUID
  FK execution_id UUID -> executions.execution_id [CASCADE]
  step_id VARCHAR(128)
  tool_name VARCHAR(128)
  server_name VARCHAR(64)
  status VARCHAR(32) [index]
  output JSONB
  error JSONB
  attempt_count INT [default: 1]
  started_at TIMESTAMPTZ
  completed_at TIMESTAMPTZ
  UNIQUE(execution_id, step_id)

audit_logs:
  PK id UUID
  FK execution_id UUID -> executions.execution_id [SET NULL]
  action VARCHAR(64) [index]
  details JSONB
  user_id VARCHAR(256)
  timestamp TIMESTAMPTZ [index]

mcp_server_states:
  PK server_name VARCHAR(64)
  connected BOOLEAN
  transport VARCHAR(16)
  mode VARCHAR(16)
  circuit_state VARCHAR(16)
  failure_count INT
  last_failure_at TIMESTAMPTZ
  last_success_at TIMESTAMPTZ
  tools_cached JSONB
  tools_cached_at TIMESTAMPTZ
  last_connected_at TIMESTAMPTZ
  last_disconnected_at TIMESTAMPTZ
  created_at TIMESTAMPTZ
  updated_at TIMESTAMPTZ
```

### 2.4 Alembic Migration Notes

**Initial migration** (`alembic revision --autogenerate -m "initial schema"`):

```python
"""Initial schema

Revision ID: 0001
Create Date: 2025-06-01

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pg_trgm extension for command text search
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        'executions',
        sa.Column('execution_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('status', sa.String(32), nullable=False, index=True),
        sa.Column('command_text', sa.Text, nullable=False),
        sa.Column('plan', postgresql.JSONB, nullable=True),
        sa.Column('results', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('context', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('execution_mode', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('planning_duration_ms', sa.Float, nullable=True),
        sa.Column('total_duration_ms', sa.Float, nullable=True),
    )

    # Create GIN indexes on JSONB columns
    op.create_index('ix_executions_plan_gin', 'executions', ['plan'], postgresql_using='gin')
    op.create_index('ix_executions_results_gin', 'executions', ['results'], postgresql_using='gin')

    op.create_table(
        'step_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('execution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('executions.execution_id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('step_id', sa.String(128), nullable=False),
        sa.Column('tool_name', sa.String(128), nullable=False),
        sa.Column('server_name', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, index=True),
        sa.Column('output', postgresql.JSONB, nullable=True),
        sa.Column('error', postgresql.JSONB, nullable=True),
        sa.Column('attempt_count', sa.Integer, nullable=False, server_default='1'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('execution_id', 'step_id', name='uq_step_per_execution'),
    )

    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('execution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('executions.execution_id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('action', sa.String(64), nullable=False, index=True),
        sa.Column('details', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('user_id', sa.String(256), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, index=True),
    )

    op.create_table(
        'mcp_server_states',
        sa.Column('server_name', sa.String(64), primary_key=True),
        sa.Column('connected', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('transport', sa.String(16), nullable=False),
        sa.Column('mode', sa.String(16), nullable=False),
        sa.Column('circuit_state', sa.String(16), nullable=False, server_default='closed'),
        sa.Column('failure_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('last_failure_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('tools_cached', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('tools_cached_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_connected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_disconnected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('mcp_server_states')
    op.drop_table('audit_logs')
    op.drop_table('step_results')
    op.drop_table('executions')
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
```

### 2.5 Query Patterns

| Pattern | SQLAlchemy Query | Index Used |
|---|---|---|
| List executions by status | `select(Execution).where(Execution.status == s).order_by(Execution.created_at.desc())` | `ix_executions_status_created` |
| List executions by mode + date | `select(Execution).where(Execution.execution_mode == m, Execution.created_at >= d)` | `ix_executions_mode_created` |
| Search command text | `select(Execution).where(Execution.command_text.ilike(f"%{q}%"))` | trigram (PostgreSQL-specific) |
| Get execution with all steps | `select(Execution).options(selectinload(Execution.step_results)).where(Execution.execution_id == id)` | PK |
| Get step results for execution | `select(StepResult).where(StepResult.execution_id == id).order_by(StepResult.started_at)` | `ix_step_results_execution_status` |
| Audit trail for execution | `select(AuditLog).where(AuditLog.execution_id == id).order_by(AuditLog.timestamp)` | `ix_audit_logs_execution_action` |
| Recent audit logs | `select(AuditLog).where(AuditLog.timestamp >= since).order_by(AuditLog.timestamp.desc())` | `ix_audit_logs_timestamp` |
| Archive old executions | `select(Execution).where(Execution.created_at < cutoff, Execution.status.in_(["completed","failed","cancelled"]))` | `ix_executions_status_created` |

---

## 3. Pydantic Models

All models use **Pydantic v2** with `BaseModel` and strict validation.

### 3.1 Core Domain Models

```python
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


# ─── Enums ──────────────────────────────────────────────────────────────

class ExecutionStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    SKIPPED_DUE_TO_DEPENDENCY = "skipped_due_to_dependency"
    RETRYING = "retrying"


class ErrorType(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


class ExecutionMode(str, Enum):
    MOCK = "mock"
    LIVE = "live"
    MIXED = "mixed"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IntentType(str, Enum):
    QUERY = "query"
    ACTION = "action"
    ANALYZE = "analyze"
    NOTIFY = "notify"
    CORRELATE = "correlate"
    REMEDIATE = "remediate"


class CircuitState(str, Enum):
    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"


# ─── CommandRequest / CommandResponse ───────────────────────────────────

class CommandRequest(BaseModel):
    """[FR-01, FR-09] User command submission."""
    text: str = Field(..., min_length=1, max_length=2000, description="Natural language command")
    auto_approve: bool = Field(default=False, description="Skip confirmation for single-step plans")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Optional client metadata")
    execution_mode_override: Literal["mock", "live", "mixed"] | None = Field(
        default=None, description="Per-command execution mode override"
    )


class CommandResponse(BaseModel):
    """[FR-01] Immediate command acceptance response."""
    execution_id: UUID
    status: ExecutionStatus = ExecutionStatus.PENDING
    message: str = "Command accepted, processing started"
    execution_mode: str
    stream_url: str  # /stream/{execution_id}


# ─── Intent Classification ──────────────────────────────────────────────

class ExtractedEntity(BaseModel):
    """[FR-03] Single extracted entity from command text."""
    type: str  # "service_name", "time_range", "threshold", "resource_id", "severity", "channel"
    value: Any
    raw_text: str  # Original matched text
    confidence: float = Field(ge=0.0, le=1.0)
    resolved: bool = False  # Whether ambiguity was resolved


class IntentClassification(BaseModel):
    """[FR-02] Classified intent from command text."""
    intent_types: list[IntentType] = Field(..., min_length=1, description="Primary intent types (multi-label)")
    entities: list[ExtractedEntity] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall classification confidence")
    command_summary: str = Field(..., description="1-sentence summary of understood intent")
    requires_clarification: bool = Field(default=False)
    clarification_prompt: str | None = None


# ─── Execution Plan ─────────────────────────────────────────────────────

class PlanStep(BaseModel):
    """[FR-06, FR-07] Single step in an execution plan DAG."""
    id: str = Field(..., description="Unique step identifier (e.g., 'step-1')")
    tool_name: str = Field(..., description="MCP tool to call")
    server: str = Field(..., description="MCP server name")
    description: str = Field(..., description="Human-readable step description")
    input_mapping: dict[str, str] = Field(
        default_factory=dict,
        description="Jinja2-like template mapping: {param: '{{step_id.output_field}}'}"
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="Expected output shape as JSON Schema"
    )
    critical: bool = Field(
        default=False,
        description="If True, execution halts on failure [FR-18]"
    )
    condition: str | None = Field(
        default=None,
        description="Jinja2 conditional expression [FR-15]"
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="step_ids that must complete before this step runs"
    )
    estimated_duration_ms: int = Field(default=1000)

    @model_validator(mode='after')
    def check_critical_destructive(self) -> 'PlanStep':
        """Auto-mark destructive operations as critical."""
        destructive_tools = {"restart_pod", "restart_service", "delete", "modify"}
        if self.tool_name in destructive_tools and not self.critical:
            self.critical = True
        return self


class ExecutionPlan(BaseModel):
    """[FR-06] Complete execution plan as a DAG."""
    plan_id: str = Field(default_factory=lambda: str(uuid4())[:8])
    template_used: str | None = Field(
        default=None,
        description="Template name if matched, null if zero-shot"
    )
    steps: list[PlanStep] = Field(..., min_length=1)
    dependencies: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Adjacency list: {step_id -> [dependent_step_ids]}"
    )
    estimated_duration_ms: int = Field(default=0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)
    explanation: str = Field(default="", description="Human-readable plan explanation")

    @model_validator(mode='after')
    def validate_dag(self) -> 'ExecutionPlan':
        """Validate no cycles and all dependencies exist."""
        step_ids = {s.id for s in self.steps}
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    raise ValueError(f"Step '{step.id}' depends on unknown step '{dep}'")
        # Cycle detection via DFS
        visited = set()
        rec_stack = set()
        def has_cycle(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbor in self.dependencies.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.remove(node)
            return False
        for step_id in step_ids:
            if step_id not in visited:
                if has_cycle(step_id):
                    raise ValueError("Execution plan contains a cycle")
        return self

    @model_validator(mode='after')
    def compute_risk_level(self) -> 'ExecutionPlan':
        """[FR-09] Auto-compute risk level from critical steps."""
        has_critical = any(s.critical for s in self.steps)
        has_write = any(s.tool_name in {"restart_pod", "restart_service", "send_message"} for s in self.steps)
        if has_critical and has_write:
            self.risk_level = RiskLevel.HIGH
        elif has_critical or has_write:
            self.risk_level = RiskLevel.MEDIUM
        else:
            self.risk_level = RiskLevel.LOW
        return self


# ─── Step Result ────────────────────────────────────────────────────────

class StepError(BaseModel):
    """[FR-20] Detailed error information for a failed step."""
    classification: ErrorType
    message: str
    retryable: bool
    attempt_count: int = Field(default=1, ge=1, le=3)
    server_name: str | None = None
    tool_name: str | None = None
    input_params: dict[str, Any] | None = Field(
        default=None,
        description="Sanitized input parameters (secrets redacted)"
    )
    root_cause: str | None = None
    suggested_remediation: list[str] = Field(default_factory=list)
    stack_trace: str | None = Field(
        default=None,
        description="Only included in DEBUG mode [FR-20]"
    )


class StepResult(BaseModel):
    """Outcome of a single plan step execution."""
    step_id: str
    status: StepStatus
    tool_name: str
    server_name: str
    output: Any = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: StepError | None = None
    duration_ms: float | None = None
    attempt_count: int = 1


# ─── Execution Context ──────────────────────────────────────────────────

class ExecutionContext(BaseModel):
    """[FR-14] Mutable context object passed between steps (copy-on-write)."""
    variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Step outputs available as variables for downstream steps"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Execution-level metadata (user info, request context)"
    )
    secrets_redacted: bool = Field(default=True)

    def with_variable(self, key: str, value: Any) -> "ExecutionContext":
        """Return new context with added variable (immutable update)."""
        new_vars = dict(self.variables)
        new_vars[key] = value
        return self.model_copy(update={"variables": new_vars})


# ─── Execution State ────────────────────────────────────────────────────

class ExecutionState(BaseModel):
    """[FR-21] Full execution state persisted after every step."""
    execution_id: UUID
    status: ExecutionStatus
    command_text: str
    execution_mode: str
    plan: ExecutionPlan | None = None
    results: dict[str, StepResult] = Field(default_factory=dict)
    context: ExecutionContext = Field(default_factory=ExecutionContext)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    planning_duration_ms: float | None = None
    total_duration_ms: float | None = None


# ─── Audit Log ──────────────────────────────────────────────────────────

class AuditLogEntry(BaseModel):
    """[FR-25, FR-26] Single audit log entry."""
    id: UUID | None = None
    execution_id: UUID | None = None
    action: str  # See audit_logs.action enum values
    details: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ─── Health & Admin ─────────────────────────────────────────────────────

class HealthCheckDetail(BaseModel):
    """Individual health check component result."""
    status: Literal["ok", "warning", "critical"]
    response_time_ms: float
    detail: str | None = None


class HealthResponse(BaseModel):
    """[FR-27] Health check response."""
    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    uptime_seconds: float
    timestamp: datetime
    checks: dict[str, HealthCheckDetail]


class ModeConfiguration(BaseModel):
    """[FR-29, FR-32] Execution mode configuration."""
    global_mode: Literal["mock", "live", "mixed"]
    server_overrides: dict[str, Literal["mock", "live", "local"]] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_mixed_overrides(self) -> 'ModeConfiguration':
        """Server overrides only valid when global_mode is 'mixed'."""
        if self.global_mode != "mixed" and self.server_overrides:
            raise ValueError("server_overrides only valid when global_mode='mixed'")
        return self
```

### 3.2 MCP Tool Schemas

Each MCP tool has a typed input schema (what the orchestrator sends) and output schema (what the MCP server returns). These schemas are shared between live and mock implementations (NFR-23).

#### Tavily Search Schemas

```python
class TavilySearchInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    max_results: int = Field(default=5, ge=1, le=20)
    search_depth: Literal["basic", "advanced"] = "basic"

class TavilySearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float = Field(ge=0.0, le=1.0)

class TavilySearchOutput(BaseModel):
    results: list[TavilySearchResult]
    query: str
    total_results: int

class TavilyAnswerInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    include_sources: bool = True

class TavilyAnswerOutput(BaseModel):
    answer: str
    sources: list[TavilySearchResult] | None = None
```

#### GitHub Schemas

```python
class GitHubRepoInfoInput(BaseModel):
    owner: str
    repo: str

class GitHubRepoInfoOutput(BaseModel):
    name: str
    full_name: str
    description: str | None
    stars: int
    forks: int
    open_issues: int
    default_branch: str
    language: str | None
    updated_at: str

class GitHubWorkflowStatusInput(BaseModel):
    owner: str
    repo: str
    branch: str = Field(default="main")

class WorkflowRun(BaseModel):
    id: int
    name: str
    status: Literal["queued", "in_progress", "completed"]
    conclusion: Literal["success", "failure", "cancelled", "skipped", "timed_out"] | None
    created_at: str
    html_url: str

class GitHubWorkflowStatusOutput(BaseModel):
    branch: str
    runs: list[WorkflowRun]

class GitHubPRChecksInput(BaseModel):
    owner: str
    repo: str
    pr_number: int = Field(..., ge=1)

class CheckRun(BaseModel):
    name: str
    status: Literal["queued", "in_progress", "completed"]
    conclusion: Literal["success", "failure", "neutral", "cancelled", "skipped", "timed_out", "action_required"] | None

class GitHubPRChecksOutput(BaseModel):
    pr_number: int
    check_runs: list[CheckRun]
```

#### Slack Schemas

```python
class SlackSendMessageInput(BaseModel):
    channel: str = Field(..., pattern=r"^#[a-z0-9_-]+$")
    text: str = Field(..., min_length=1, max_length=3000)
    thread_ts: str | None = None  # For threaded replies

class SlackSendMessageOutput(BaseModel):
    ok: bool
    channel: str
    ts: str  # Message timestamp (Slack's message ID)
    delivery_status: Literal["delivered", "queued", "failed"]
```

#### Jira Schemas

```python
class JiraSearchTicketsInput(BaseModel):
    jql: str = Field(..., min_length=1, description="JQL query string")
    max_results: int = Field(default=50, ge=1, le=100)

class JiraTicket(BaseModel):
    key: str
    summary: str
    status: str
    priority: str
    assignee: str | None
    created: str
    updated: str

class JiraSearchTicketsOutput(BaseModel):
    tickets: list[JiraTicket]
    total: int

class JiraCreateIncidentInput(BaseModel):
    summary: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    priority: Literal["Highest", "High", "Medium", "Low", "Lowest"] = "High"
    labels: list[str] = Field(default_factory=lambda: ["incident", "auto-generated"])

class JiraCreateIncidentOutput(BaseModel):
    key: str
    url: str
    status: str
```

#### AWS ECS Schemas

```python
class AWSDescribePodsInput(BaseModel):
    namespace: str = Field(..., pattern=r"^[a-z0-9-]+$")
    service: str = Field(..., pattern=r"^[a-z0-9-]+$")

class PodStatus(BaseModel):
    name: str
    namespace: str
    status: Literal["Running", "Pending", "CrashLoopBackOff", "Error", "Succeeded"]
    restarts: int
    cpu_percent: float = Field(ge=0.0, le=100.0)
    memory_percent: float = Field(ge=0.0, le=100.0)
    age: str
    node: str | None = None

class AWSDescribePodsOutput(BaseModel):
    pods: list[PodStatus]
    namespace: str
    service: str
    total_pods: int

class AWSGetMetricsInput(BaseModel):
    namespace: str
    service: str
    metric: Literal["cpu", "memory", "requests", "errors", "latency"]
    duration_minutes: int = Field(default=120, ge=5, le=10080)  # 5 min to 7 days

class MetricDatapoint(BaseModel):
    timestamp: str
    value: float
    unit: str

class AWSGetMetricsOutput(BaseModel):
    metric: str
    datapoints: list[MetricDatapoint]
    statistics: dict[str, float]  # {"avg": x, "min": y, "max": z, "p99": w}

class AWSRestartPodInput(BaseModel):
    namespace: str
    pod_name: str
    graceful: bool = True

class AWSRestartPodOutput(BaseModel):
    pod_name: str
    namespace: str
    previous_status: str
    restart_initiated: bool
    message: str
```

#### PostgreSQL DB Schemas (READ-ONLY enforcement)

```python
class PostgresExecuteQueryInput(BaseModel):
    sql: str = Field(..., min_length=1)
    params: list[Any] = Field(default_factory=list)

    @field_validator("sql")
    @classmethod
    def reject_write_operations(cls, v: str) -> str:
        """[NFR-13] Block destructive SQL at the schema level."""
        write_keywords = {"insert", "update", "delete", "drop", "alter", "create", "truncate", "grant", "revoke"}
        first_token = v.strip().split()[0].lower()
        if first_token in write_keywords:
            raise ValueError(f"Write operations are blocked. Found: '{first_token.upper()}'")
        return v

class PostgresExecuteQueryOutput(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    execution_time_ms: float
```

#### Calculator Schemas

```python
class CalculatorMathInput(BaseModel):
    expression: str = Field(..., min_length=1, max_length=500, description="Math expression e.g., '(100 - 80) / 80 * 100'")

class CalculatorMathOutput(BaseModel):
    result: float
    expression: str
    unit: str | None = None

class CalculatorDateInput(BaseModel):
    expression: str = Field(..., description="Date expression e.g., 'now - 7 days', 'days_between(2024-01-01, 2024-06-01)'")

class CalculatorDateOutput(BaseModel):
    result: str
    expression: str
    result_type: Literal["datetime", "duration", "error"]

class CalculatorThresholdInput(BaseModel):
    value: float
    operator: Literal[">", ">=", "<", "<=", "==", "!="]
    threshold: float

class CalculatorThresholdOutput(BaseModel):
    triggered: bool
    value: float
    operator: str
    threshold: float
    message: str  # e.g., "CPU 85.2% > threshold 80%: TRIGGERED"
```

### 3.3 WebSocket / SSE Event Models

```python
class SSEEvent(BaseModel):
    """Base for all SSE events."""
    event_type: str
    data: dict[str, Any]
    id: str | None = None  # Event sequence number

class StreamEventType(str, Enum):
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
```

### 3.4 Pydantic-Settings Configuration Model

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class MCPSettings(BaseModel):
    """Configuration for a single MCP server."""
    transport: Literal["stdio", "sse"] = "stdio"
    command: list[str] | None = None  # Required for stdio transport
    url: str | None = None  # Required for sse transport
    mode: Literal["mock", "live", "local"] = "mock"
    timeout: int = Field(default=30, ge=1, le=300)
    env: dict[str, str] = Field(default_factory=dict)
    critical: bool = False  # If True, health check fails when disconnected

class LLMSettings(BaseModel):
    """LLM provider configuration."""
    provider: Literal["openai"] = "openai"
    model: str = "gpt-4o"
    api_key: str = Field(default="", description="Set via OPENAI_API_KEY env var")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=128000)
    planning_timeout_ms: int = Field(default=5000, ge=1000, le=30000)

class DatabaseSettings(BaseModel):
    url: str = "postgresql+asyncpg://opsmate:opsmate@localhost:5432/opsmate"
    pool_size: int = Field(default=10, ge=1, le=100)
    max_overflow: int = Field(default=20, ge=0, le=100)
    echo: bool = False

class CacheSettings(BaseModel):
    url: str = "redis://localhost:6379/0"
    ttl: int = Field(default=3600, ge=60)
    circuit_breaker_ttl: int = Field(default=30, description="Circuit breaker state TTL in seconds")

class LoggingSettings(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: Literal["json", "text"] = "json"
    output: Literal["stdout", "stderr", "file"] = "stdout"
    file_path: str | None = None

class AppSettings(BaseModel):
    name: str = "mcp-opsmate"
    version: str = "1.0.0"
    execution_mode: Literal["mock", "live", "mixed"] = "mock"
    auto_approve: bool = False
    max_concurrent_steps: int = Field(default=10, ge=1, le=50)
    plan_confirmation_required: bool = True
    retention_days: int = Field(default=30, ge=1)

class OpsMateConfig(BaseSettings):
    """Root configuration loaded via Pydantic-Settings.

    Resolution order: default values -> config.yaml -> env vars (OPS_MATE_*) -> CLI flags
    """
    model_config = SettingsConfigDict(
        env_prefix="OPS_MATE_",
        env_nested_delimiter="__",
        yaml_file="config.yaml",
        extra="ignore",
    )

    app: AppSettings = Field(default_factory=AppSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    mcp_servers: dict[str, MCPSettings] = Field(default_factory=dict)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    # Auth
    api_key: str = Field(default="dev-api-key-change-in-production")
    admin_api_token: str = Field(default="dev-admin-token-change-in-production")
```



---

## 4. MCP Server Interface Definitions

Each MCP server is a standalone Python process communicating via the MCP protocol. The orchestrator (`infra/mcp_hub.py`) manages their lifecycle and routes tool calls. All servers implement a common base class.

### 4.1 Base MCP Server

```python
# opsmate/mcp_servers/base.py
from abc import ABC, abstractmethod
from typing import Any, Callable

from mcp.server import Server as MCPServer
from mcp.server.stdio import stdio_server


class BaseMCPServer(ABC):
    """Abstract base class for all MCP servers in opsmate.

    Each server is a standalone process that:
    1. Registers tools with the MCP Server instance
    2. Handles tool calls via the MCP protocol
    3. Runs in either LIVE or MOCK mode based on environment
    """

    def __init__(self, name: str, version: str = "1.0.0"):
        self.name = name
        self.server = MCPServer(name)
        self._register_tools()

    @abstractmethod
    def _register_tools(self) -> None:
        """Register all tool handlers with self.server."""
        ...

    async def run_stdio(self) -> None:
        """Run as stdio MCP server (primary transport)."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream, write_stream,
                self.server.create_initialization_options()
            )
```

### 4.2 Error Modes (Common to All Servers)

| Error Code | HTTP/MCP Status | Trigger | Retryable |
|---|---|---|---|
| `MCP_TOOL_NOT_FOUND` | `-32601` | Tool name not registered | No |
| `MCP_INVALID_PARAMS` | `-32602` | Schema validation failure | No |
| `MCP_INTERNAL_ERROR` | `-32603` | Unhandled server exception | Maybe |
| `TIMEOUT` | `408` | Tool execution exceeded timeout | Yes |
| `RATE_LIMITED` | `429` | External API rate limit | Yes (respect Retry-After) |
| `AUTHENTICATION_FAILED` | `401` | Invalid credentials | No |
| `PERMISSION_DENIED` | `403` | Valid auth, insufficient permissions | No |
| `RESOURCE_NOT_FOUND` | `404` | Requested resource does not exist | No |
| `SERVICE_UNAVAILABLE` | `503` | External API temporarily down | Yes |

### 4.3 Server 1: tavily-search

| Attribute | Value |
|---|---|
| **Server Name** | `tavily-search` |
| **Description** | Web search and question answering via Tavily API |
| **Env Vars Required (LIVE)** | `TAVILY_API_KEY` |
| **Mode Support** | MOCK, LIVE |
| **Req. IDs** | FR-03 (entity search) |

#### Tools

| Tool Name | Input Schema | Output Schema | Description |
|---|---|---|---|
| `search` | `TavilySearchInput` | `TavilySearchOutput` | Perform web search, return ranked results |
| `answer` | `TavilyAnswerInput` | `TavilyAnswerOutput` | Search + synthesize an answer with sources |

#### Mock Implementation

```python
# opsmate/mcp_servers/tavily/mock.py
from faker import Faker

class TavilyMock:
    """Deterministic mock for Tavily search tools."""

    def __init__(self, seed: int):
        self.faker = Faker()
        self.faker.seed_instance(seed)

    async def search(self, query: str, max_results: int = 5, **kwargs) -> dict:
        await self._inject_latency(50, 150)
        results = []
        for i in range(min(max_results, 10)):
            domain = self.faker.domain_name()
            results.append({
                "title": self.faker.sentence(nb_words=8),
                "url": f"https://{domain}/{self.faker.uri_path()}",
                "content": self.faker.paragraph(nb_sentences=3),
                "score": round(self.faker.random.uniform(0.5, 0.99), 2),
            })
        return {
            "results": results,
            "query": query,
            "total_results": len(results),
        }

    async def answer(self, query: str, include_sources: bool = True, **kwargs) -> dict:
        await self._inject_latency(100, 200)
        answer_text = self.faker.paragraph(nb_sentences=5)
        sources = None
        if include_sources:
            sources = (await self.search(query, max_results=3))["results"]
        return {
            "answer": answer_text,
            "sources": sources,
        }

    async def _inject_latency(self, min_ms: int, max_ms: int) -> None:
        import asyncio, random
        await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)
```

### 4.4 Server 2: github

| Attribute | Value |
|---|---|
| **Server Name** | `github` |
| **Description** | GitHub repository information, CI status, PR checks |
| **Env Vars Required (LIVE)** | `GITHUB_PAT` |
| **Mode Support** | MOCK, LIVE |
| **Req. IDs** | US-2 (CI correlation) |

#### Tools

| Tool Name | Input Schema | Output Schema | Destructive |
|---|---|---|---|
| `repo_info` | `GitHubRepoInfoInput` | `GitHubRepoInfoOutput` | No |
| `workflow_status` | `GitHubWorkflowStatusInput` | `GitHubWorkflowStatusOutput` | No |
| `pr_checks` | `GitHubPRChecksInput` | `GitHubPRChecksOutput` | No |

#### Mock Implementation

```python
# opsmate/mcp_servers/github/mock.py
class GitHubMock:
    """Deterministic mock for GitHub tools."""

    def __init__(self, seed: int):
        self.faker = Faker()
        self.faker.seed_instance(seed)

    async def repo_info(self, owner: str, repo: str, **kwargs) -> dict:
        await self._inject_latency(50, 120)
        return {
            "name": repo,
            "full_name": f"{owner}/{repo}",
            "description": self.faker.sentence(nb_words=10),
            "stars": self.faker.random_int(min=10, max=50000),
            "forks": self.faker.random_int(min=0, max=5000),
            "open_issues": self.faker.random_int(min=0, max=200),
            "default_branch": self.faker.random_element(["main", "master"]),
            "language": self.faker.random_element(["Python", "Go", "TypeScript", "Java", "Rust"]),
            "updated_at": self.faker.iso8601(),
        }

    async def workflow_status(self, owner: str, repo: str, branch: str = "main", **kwargs) -> dict:
        await self._inject_latency(80, 180)
        statuses = ["queued", "in_progress", "completed"]
        conclusions = ["success", "failure", "cancelled", None]
        runs = []
        for i in range(self.faker.random_int(min=1, max=5)):
            runs.append({
                "id": self.faker.random_int(min=1000000, max=9999999),
                "name": self.faker.random_element(["CI", "Build", "Test", "Deploy", "Lint"]),
                "status": self.faker.random_element(statuses),
                "conclusion": self.faker.random_element(conclusions),
                "created_at": self.faker.iso8601(),
                "html_url": f"https://github.com/{owner}/{repo}/actions/runs/{self.faker.random_int(min=1, max=999999)}",
            })
        return {"branch": branch, "runs": runs}

    async def pr_checks(self, owner: str, repo: str, pr_number: int, **kwargs) -> dict:
        await self._inject_latency(60, 150)
        check_names = ["unit-tests", "integration-tests", "lint", "security-scan", "build"]
        check_runs = []
        for name in check_names[:self.faker.random_int(min=3, max=5)]:
            check_runs.append({
                "name": name,
                "status": "completed",
                "conclusion": self.faker.random_element(["success", "failure", "neutral"]),
            })
        return {"pr_number": pr_number, "check_runs": check_runs}
```

### 4.5 Server 3: slack

| Attribute | Value |
|---|---|
| **Server Name** | `slack` |
| **Description** | Slack message delivery |
| **Env Vars Required (LIVE)** | `SLACK_WEBHOOK_URL` |
| **Mode Support** | MOCK, LIVE |
| **Req. IDs** | US-1 (alerting), FR-33 |

#### Tools

| Tool Name | Input Schema | Output Schema | Destructive |
|---|---|---|---|
| `send_message` | `SlackSendMessageInput` | `SlackSendMessageOutput` | Yes (sends real messages) |

#### Mock Implementation

```python
# opsmate/mcp_servers/slack/mock.py
class SlackMock:
    """Deterministic mock for Slack tools."""

    def __init__(self, seed: int):
        self.faker = Faker()
        self.faker.seed_instance(seed)
        self._sent_messages: list[dict] = []

    async def send_message(self, channel: str, text: str, thread_ts: str | None = None, **kwargs) -> dict:
        await self._inject_latency(50, 100)
        message_id = f"{self.faker.random_int(min=1000000000, max=9999999999)}.{self.faker.random_int(min=100000, max=999999)}"
        result = {
            "ok": True,
            "channel": channel,
            "ts": message_id,
            "delivery_status": "delivered",
        }
        self._sent_messages.append({"channel": channel, "text": text, "ts": message_id})
        return result

    # Utility for tests: inspect sent messages
    def get_sent_messages(self) -> list[dict]:
        return list(self._sent_messages)
```

### 4.6 Server 4: jira

| Attribute | Value |
|---|---|
| **Server Name** | `jira` |
| **Description** | Jira ticket search and incident creation |
| **Env Vars Required (LIVE)** | `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` |
| **Mode Support** | MOCK, LIVE |
| **Req. IDs** | US-2 (ticket correlation) |

#### Tools

| Tool Name | Input Schema | Output Schema | Destructive |
|---|---|---|---|
| `search_tickets` | `JiraSearchTicketsInput` | `JiraSearchTicketsOutput` | No |
| `create_incident` | `JiraCreateIncidentInput` | `JiraCreateIncidentOutput` | Yes (creates tickets) |

#### Mock Implementation

```python
# opsmate/mcp_servers/jira/mock.py
class JiraMock:
    """Deterministic mock for Jira tools."""

    PRIORITY_MAP = {"Highest": 1, "High": 2, "Medium": 3, "Low": 4, "Lowest": 5}

    def __init__(self, seed: int):
        self.faker = Faker()
        self.faker.seed_instance(seed)
        self._incident_counter = seed % 1000

    async def search_tickets(self, jql: str, max_results: int = 50, **kwargs) -> dict:
        await self._inject_latency(80, 200)
        priorities = ["Highest", "High", "Medium", "Low"]
        statuses = ["Open", "In Progress", "Resolved", "Closed"]
        tickets = []
        count = min(max_results, self.faker.random_int(min=0, max=20))
        for i in range(count):
            project = self.faker.random_element(["OPS", "INFRA", "SRE", "DEV", "PLAT"])
            ticket_num = self.faker.random_int(min=1, max=9999)
            tickets.append({
                "key": f"{project}-{ticket_num}",
                "summary": self.faker.sentence(nb_words=8),
                "status": self.faker.random_element(statuses),
                "priority": self.faker.random_element(priorities),
                "assignee": self.faker.email() if self.faker.boolean(chance_of_getting_true=70) else None,
                "created": self.faker.iso8601(),
                "updated": self.faker.iso8601(),
            })
        return {"tickets": tickets, "total": count}

    async def create_incident(self, summary: str, description: str, priority: str = "High", labels: list[str] | None = None, **kwargs) -> dict:
        await self._inject_latency(60, 150)
        self._incident_counter += 1
        return {
            "key": f"INC-{self._incident_counter}",
            "url": f"https://jira.example.com/browse/INC-{self._incident_counter}",
            "status": "Open",
        }
```

### 4.7 Server 5: aws-ecs

| Attribute | Value |
|---|---|
| **Server Name** | `aws-ecs` |
| **Description** | AWS ECS/EKS pod management and CloudWatch metrics |
| **Env Vars Required (LIVE)** | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` |
| **Mode Support** | MOCK, LIVE |
| **Req. IDs** | US-1 (health check), FR-15 (conditional restart) |

#### Tools

| Tool Name | Input Schema | Output Schema | Destructive |
|---|---|---|---|
| `describe_pods` | `AWSDescribePodsInput` | `AWSDescribePodsOutput` | No |
| `get_metrics` | `AWSGetMetricsInput` | `AWSGetMetricsOutput` | No |
| `restart_pod` | `AWSRestartPodInput` | `AWSRestartPodOutput` | **YES** |

#### Mock Implementation

```python
# opsmate/mcp_servers/aws_ecs/mock.py
class AWSECSMock:
    """[FR-30, NFR-23] Deterministic mock for AWS ECS tools with realistic data."""

    def __init__(self, seed: int):
        self.faker = Faker()
        self.faker.seed_instance(seed)
        self._restarted_pods: set[str] = set()

    async def describe_pods(self, namespace: str, service: str, **kwargs) -> dict:
        await self._inject_latency(80, 180)
        pod_count = self.faker.random_int(min=2, max=10)
        statuses = ["Running", "Running", "Running", "Pending", "CrashLoopBackOff"]
        pods = []
        for i in range(pod_count):
            pod_name = f"{service}-{self.faker.hexify(text='^^^^^^^', upper=False)}-{i}"
            pods.append({
                "name": pod_name,
                "namespace": namespace,
                "status": self.faker.random_element(statuses),
                "restarts": self.faker.random_int(min=0, max=5),
                "cpu_percent": round(self.faker.random.uniform(5, 98), 1),
                "memory_percent": round(self.faker.random.uniform(10, 90), 1),
                "age": f"{self.faker.random_int(min=1, max=72)}h",
                "node": f"ip-10-0-{self.faker.random_int(min=1, max=255)}-{self.faker.random_int(min=1, max=99)}.ec2.internal",
            })
        return {
            "pods": pods,
            "namespace": namespace,
            "service": service,
            "total_pods": len(pods),
        }

    async def get_metrics(self, namespace: str, service: str, metric: str, duration_minutes: int = 120, **kwargs) -> dict:
        await self._inject_latency(100, 250)
        import random, statistics
        # Generate time-series data
        datapoints = []
        base_value = {"cpu": 45.0, "memory": 60.0, "requests": 100.0, "errors": 2.0, "latency": 50.0}.get(metric, 50.0)
        for i in range(duration_minutes // 5):
            value = base_value + random.gauss(0, base_value * 0.15)
            datapoints.append({
                "timestamp": f"2025-01-01T{i//12:02d}:{(i%12)*5:02d}:00Z",
                "value": round(max(0, value), 2),
                "unit": {"cpu": "Percent", "memory": "Percent", "requests": "Count", "errors": "Count", "latency": "Milliseconds"}.get(metric, "Count"),
            })
        values = [d["value"] for d in datapoints]
        return {
            "metric": metric,
            "datapoints": datapoints,
            "statistics": {
                "avg": round(statistics.mean(values), 2),
                "min": round(min(values), 2),
                "max": round(max(values), 2),
                "p99": round(sorted(values)[int(len(values)*0.99)], 2),
            },
        }

    async def restart_pod(self, namespace: str, pod_name: str, graceful: bool = True, **kwargs) -> dict:
        await self._inject_latency(200, 500)
        self._restarted_pods.add(pod_name)
        return {
            "pod_name": pod_name,
            "namespace": namespace,
            "previous_status": "Running",
            "restart_initiated": True,
            "message": f"Pod {pod_name} restart initiated (graceful={graceful})",
        }
```

### 4.8 Server 6: postgres-db

| Attribute | Value |
|---|---|
| **Server Name** | `postgres-db` |
| **Description** | Read-only PostgreSQL query execution |
| **Env Vars Required (LIVE)** | `DATABASE_URL` |
| **Mode Support** | MOCK, LIVE |
| **Security** | READ-ONLY enforced at schema + implementation level |
| **Req. IDs** | NFR-13 (no injection), US-3 (metric analysis) |

#### Tools

| Tool Name | Input Schema | Output Schema | Destructive |
|---|---|---|---|
| `execute_query` | `PostgresExecuteQueryInput` | `PostgresExecuteQueryOutput` | **No — blocked by schema validator** |
| `get_tables` | `{}` | `{"tables": ["table1", "table2", ...]}` | No |

#### Mock Implementation

```python
# opsmate/mcp_servers/postgres/mock.py
class PostgresMock:
    """Deterministic mock for read-only PostgreSQL queries."""

    # Synthetic database schema
    MOCK_TABLES = {
        "lambda_invocations": [
            {"column_name": "function_name", "data_type": "varchar"},
            {"column_name": "invocation_date", "data_type": "date"},
            {"column_name": "duration_ms", "data_type": "float"},
            {"column_name": "memory_mb", "data_type": "int"},
            {"column_name": "cold_start", "data_type": "boolean"},
        ],
        "ecs_services": [
            {"column_name": "service_name", "data_type": "varchar"},
            {"column_name": "cluster", "data_type": "varchar"},
            {"column_name": "running_count", "data_type": "int"},
            {"column_name": "desired_count", "data_type": "int"},
            {"column_name": "cpu_utilization", "data_type": "float"},
        ],
        "deployments": [
            {"column_name": "service", "data_type": "varchar"},
            {"column_name": "version", "data_type": "varchar"},
            {"column_name": "deployed_at", "data_type": "timestamp"},
            {"column_name": "status", "data_type": "varchar"},
        ],
    }

    def __init__(self, seed: int):
        self.faker = Faker()
        self.faker.seed_instance(seed)

    async def execute_query(self, sql: str, params: list | None = None, **kwargs) -> dict:
        await self._inject_latency(30, 120)
        # Return synthetic results based on FROM clause
        lower_sql = sql.lower()
        if "lambda_invocations" in lower_sql:
            return self._mock_lambda_results()
        elif "ecs_services" in lower_sql:
            return self._mock_ecs_results()
        elif "deployments" in lower_sql:
            return self._mock_deployment_results()
        else:
            return {"columns": ["result"], "rows": [["Mock query executed"]], "row_count": 1, "execution_time_ms": 15.2}

    async def get_tables(self, **kwargs) -> dict:
        return {"tables": list(self.MOCK_TABLES.keys())}

    def _mock_lambda_results(self) -> dict:
        functions = ["payment-processor", "notification-sender", "auth-validator", "report-generator", "data-transformer"]
        rows = []
        for fn in functions:
            for day in range(7):
                rows.append([
                    fn,
                    f"2025-05-{25 + day:02d}",
                    round(self.faker.random.uniform(50, 800), 1),
                    self.faker.random_element([128, 256, 512, 1024]),
                    self.faker.boolean(chance_of_getting_true=20),
                ])
        return {
            "columns": ["function_name", "invocation_date", "duration_ms", "memory_mb", "cold_start"],
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": round(self.faker.random.uniform(5, 50), 1),
        }

    def _mock_ecs_results(self) -> dict:
        services = ["payment-service", "api-gateway", "user-service", "order-service", "inventory-service"]
        rows = [[s, "prod-cluster", self.faker.random_int(2, 10), self.faker.random_int(2, 10),
                 round(self.faker.random.uniform(20, 85), 1)] for s in services]
        return {
            "columns": ["service_name", "cluster", "running_count", "desired_count", "cpu_utilization"],
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": round(self.faker.random.uniform(5, 30), 1),
        }

    def _mock_deployment_results(self) -> dict:
        services = ["payment-service", "api-gateway", "user-service"]
        rows = []
        for s in services:
            for i in range(3):
                rows.append([s, f"1.{self.faker.random_int(10, 99)}.{self.faker.random_int(0, 9)}",
                            f"2025-05-{self.faker.random_int(20, 30):02d}T{self.faker.random_int(0, 23):02d}:00:00Z",
                            self.faker.random_element(["success", "failed", "rolled_back"])])
        return {
            "columns": ["service", "version", "deployed_at", "status"],
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": round(self.faker.random.uniform(5, 20), 1),
        }
```

### 4.9 Server 7: calculator

| Attribute | Value |
|---|---|
| **Server Name** | `calculator` |
| **Description** | Mathematical computation, date arithmetic, threshold checks |
| **Env Vars Required** | None |
| **Mode Support** | LOCAL only (always executes locally, never mocked) |
| **Req. IDs** | FR-15 (conditional expressions), US-3 (cost calculation) |

#### Tools

| Tool Name | Input Schema | Output Schema | Destructive |
|---|---|---|---|
| `math` | `CalculatorMathInput` | `CalculatorMathOutput` | No |
| `date_calc` | `CalculatorDateInput` | `CalculatorDateOutput` | No |
| `threshold_check` | `CalculatorThresholdInput` | `CalculatorThresholdOutput` | No |

#### LIVE Implementation (no mock — always local)

```python
# opsmate/mcp_servers/calculator/server.py
import ast
import operator
from datetime import datetime, timedelta

class CalculatorServer:
    """Local-only MCP server for calculations. No external dependencies."""

    # Safe operators for math evaluation
    _SAFE_OPS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
    }

    async def math(self, expression: str, **kwargs) -> dict:
        """Safely evaluate a mathematical expression."""
        try:
            result = self._safe_eval(expression)
            return {
                "result": result,
                "expression": expression,
                "unit": None,
            }
        except Exception as e:
            return {
                "result": float("nan"),
                "expression": expression,
                "unit": None,
            }

    def _safe_eval(self, expr: str) -> float:
        """Evaluate math expression using AST — no eval/exec. [NFR-13]"""
        tree = ast.parse(expr.strip(), mode='eval')
        return self._eval_node(tree.body)

    def _eval_node(self, node: ast.AST) -> float:
        if isinstance(node, ast.Constant):
            return float(node.value)
        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in self._SAFE_OPS:
                raise ValueError(f"Unsupported operator: {op_type.__name__}")
            return self._SAFE_OPS[op_type](self._eval_node(node.left), self._eval_node(node.right))
        elif isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return -self._eval_node(node.operand)
            raise ValueError("Unsupported unary operator")
        else:
            raise ValueError(f"Unsupported AST node: {type(node).__name__}")

    async def date_calc(self, expression: str, **kwargs) -> dict:
        """Evaluate date expressions."""
        now = datetime.utcnow()
        result_type = "datetime"
        result = ""

        try:
            expr_lower = expression.lower().strip()
            if expr_lower == "now":
                result = now.isoformat()
            elif "-" in expr_lower and "day" in expr_lower:
                # Parse "now - 7 days" style
                parts = expr_lower.replace("now", "").replace("days", "").replace("day", "").split()
                delta = timedelta(days=int(parts[1]))
                result = (now - delta).isoformat()
            elif "days_between" in expr_lower:
                # Parse "days_between(2024-01-01, 2024-06-01)"
                import re
                dates = re.findall(r'(\d{4}-\d{2}-\d{2})', expr_lower)
                if len(dates) == 2:
                    d1 = datetime.strptime(dates[0], "%Y-%m-%d")
                    d2 = datetime.strptime(dates[1], "%Y-%m-%d")
                    delta = abs((d2 - d1).days)
                    result = str(delta)
                    result_type = "duration"
            else:
                result = now.isoformat()
                result_type = "datetime"
        except Exception as e:
            return {"result": f"Error: {str(e)}", "expression": expression, "result_type": "error"}

        return {"result": result, "expression": expression, "result_type": result_type}

    async def threshold_check(self, value: float, operator: str, threshold: float, **kwargs) -> dict:
        """Compare a value against a threshold."""
        ops = {
            ">": lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
            "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
        }
        triggered = ops[operator](value, threshold)
        return {
            "triggered": triggered,
            "value": value,
            "operator": operator,
            "threshold": threshold,
            "message": f"Value {value} {operator} threshold {threshold}: {'TRIGGERED' if triggered else 'OK'}",
        }
```

### 4.10 Mock Data Generator — Seed Derivation

All mock implementations use deterministic seeding for reproducibility (FR-30):

```python
def derive_seed(command_text: str, step_index: int = 0) -> int:
    """Derive a deterministic seed from command text and step index.

    Same command + step always produces identical mock data.
    """
    import hashlib
    hash_input = f"{command_text}::{step_index}".encode("utf-8")
    hash_bytes = hashlib.sha256(hash_input).digest()
    return int.from_bytes(hash_bytes[:4], byteorder="big")
```

### 4.11 Mock / Live Schema Parity Enforcement

```python
# tests/test_contract/test_schema_parity.py
import pytest
from opsmate.mcp_servers.aws_ecs.mock import AWSECSMock
from opsmate.mcp_servers.aws_ecs.server import AWSECSServer
from opsmate.core.models import AWSDescribePodsOutput, AWSGetMetricsOutput, AWSRestartPodOutput

@pytest.mark.parametrize("tool_name,schema_class", [
    ("describe_pods", AWSDescribePodsOutput),
    ("get_metrics", AWSGetMetricsOutput),
    ("restart_pod", AWSRestartPodOutput),
])
@pytest.mark.asyncio
async def test_aws_ecs_schema_parity(tool_name, schema_class):
    """[NFR-23] Mock and live responses both validate against same Pydantic model."""
    mock = AWSECSMock(seed=42)
    server = AWSECSServer()  # LIVE implementation

    # Get mock output
    mock_method = getattr(mock, tool_name)
    mock_raw = await mock_method(namespace="prod", service="payment-service")

    # Get live output (in mock environment, server also returns test data)
    server_method = getattr(server, tool_name)
    live_raw = await server_method(namespace="prod", service="payment-service")

    # Both must validate
    mock_validated = schema_class.model_validate(mock_raw)
    live_validated = schema_class.model_validate(live_raw)

    # Key structure must match
    assert set(mock_validated.model_dump().keys()) == set(live_validated.model_dump().keys())
```



---

## 5. Configuration Schema

### 5.1 Complete `config.yaml` Structure

```yaml
# ═══════════════════════════════════════════════════════════════
# mcp-opsmate Configuration File
# Resolution order: defaults → config.yaml → env vars (OPS_MATE_*) → CLI flags
# Env var interpolation: ${VAR_NAME} or ${VAR_NAME:-default}
# ═══════════════════════════════════════════════════════════════

app:
  name: "mcp-opsmate"
  version: "1.0.0"
  execution_mode: "mock"          # mock | live | mixed
  auto_approve: false             # Skip confirmation for single-step plans
  max_concurrent_steps: 10        # Max parallel steps in a single execution
  plan_confirmation_required: true
  retention_days: 30              # Execution history retention

llm:
  provider: "openai"
  model: "gpt-4o"
  api_key: "${OPENAI_API_KEY}"     # Required for LIVE mode; ignored in MOCK
  temperature: 0.2                # Low = deterministic planning
  max_tokens: 4096
  planning_timeout_ms: 5000

# ─── MCP Server Configurations ─────────────────────────────────
# Each server can override the global execution_mode.
# In MIXED mode, per-server mode determines routing for that server.
# ═══════════════════════════════════════════════════════════════

mcp_servers:
  # Web search — useful for documentation lookup
  tavily-search:
    transport: "stdio"
    command: ["python", "-m", "opsmate.mcp_servers.tavily"]
    mode: "mock"                  # Override: use mock unless explicitly set
    timeout: 30
    env:
      TAVILY_API_KEY: "${TAVILY_API_KEY}"
    critical: false               # System works without search

  # GitHub — CI/CD status and repository info
  github:
    transport: "stdio"
    command: ["python", "-m", "opsmate.mcp_servers.github"]
    mode: "mock"
    timeout: 30
    env:
      GITHUB_PAT: "${GITHUB_PAT}"
    critical: false

  # Slack — alerting and notifications
  slack:
    transport: "stdio"
    command: ["python", "-m", "opsmate.mcp_servers.slack"]
    mode: "mock"
    timeout: 15
    env:
      SLACK_WEBHOOK_URL: "${SLACK_WEBHOOK_URL}"
    critical: false

  # Jira — ticket management and incident creation
  jira:
    transport: "stdio"
    command: ["python", "-m", "opsmate.mcp_servers.jira"]
    mode: "mock"
    timeout: 30
    env:
      JIRA_URL: "${JIRA_URL}"
      JIRA_EMAIL: "${JIRA_EMAIL}"
      JIRA_API_TOKEN: "${JIRA_API_TOKEN}"
    critical: false

  # AWS ECS/EKS — pod management and metrics
  aws-ecs:
    transport: "stdio"
    command: ["python", "-m", "opsmate.mcp_servers.aws_ecs"]
    mode: "mock"                  # Default mock: requires AWS creds for live
    timeout: 60                   # Longer timeout for CloudWatch
    env:
      AWS_ACCESS_KEY_ID: "${AWS_ACCESS_KEY_ID}"
      AWS_SECRET_ACCESS_KEY: "${AWS_SECRET_ACCESS_KEY}"
      AWS_REGION: "${AWS_REGION:-us-east-1}"
    critical: true                # Health check fails if disconnected in LIVE

  # PostgreSQL — read-only database queries
  postgres-db:
    transport: "stdio"
    command: ["python", "-m", "opsmate.mcp_servers.postgres"]
    mode: "live"                  # Uses local Docker PostgreSQL
    timeout: 30
    env:
      DATABASE_URL: "${DATABASE_URL}"
    critical: false

  # Calculator — local computation, no external deps
  calculator:
    transport: "stdio"
    command: ["python", "-m", "opsmate.mcp_servers.calculator"]
    mode: "local"                 # Always local; cannot be mocked
    timeout: 5                    # Very fast — computations are local
    env: {}                       # No env vars needed
    critical: true                # Always available; health check fails if down

# ─── Data Layer ────────────────────────────────────────────────

database:
  url: "${DATABASE_URL:-postgresql+asyncpg://opsmate:opsmate@localhost:5432/opsmate}"
  pool_size: 10
  max_overflow: 20
  echo: false                    # Set true for SQL debugging

cache:
  url: "${REDIS_URL:-redis://localhost:6379/0}"
  ttl: 3600                      # General cache TTL (seconds)
  circuit_breaker_ttl: 30        # Circuit breaker state TTL

# ─── Logging ───────────────────────────────────────────────────

logging:
  level: "INFO"                  # DEBUG | INFO | WARNING | ERROR
  format: "json"                 # json | text
  output: "stdout"               # stdout | stderr | file
  file_path: null                # Required if output=file
```

### 5.2 Environment Variable Mappings

| Config Path | Env Var | Default | Required In |
|---|---|---|---|
| `app.execution_mode` | `OPS_MATE_APP__EXECUTION_MODE` | `mock` | — |
| `app.auto_approve` | `OPS_MATE_APP__AUTO_APPROVE` | `false` | — |
| `llm.api_key` | `OPENAI_API_KEY` | — | LIVE (planning) |
| `llm.model` | `OPS_MATE_LLM__MODEL` | `gpt-4o` | — |
| `llm.temperature` | `OPS_MATE_LLM__TEMPERATURE` | `0.2` | — |
| `database.url` | `DATABASE_URL` | `postgresql+asyncpg://opsmate:opsmate@localhost:5432/opsmate` | always |
| `cache.url` | `REDIS_URL` | `redis://localhost:6379/0` | always |
| `api_key` | `OPS_MATE_API_KEY` | `dev-api-key-change-in-production` | always |
| `admin_api_token` | `OPS_MATE_ADMIN_API_TOKEN` | `dev-admin-token-change-in-production` | always |
| `mcp_servers.tavily-search.env.TAVILY_API_KEY` | `TAVILY_API_KEY` | — | LIVE mode for tavily |
| `mcp_servers.github.env.GITHUB_PAT` | `GITHUB_PAT` | — | LIVE mode for github |
| `mcp_servers.slack.env.SLACK_WEBHOOK_URL` | `SLACK_WEBHOOK_URL` | — | LIVE mode for slack |
| `mcp_servers.jira.env.JIRA_URL` | `JIRA_URL` | — | LIVE mode for jira |
| `mcp_servers.jira.env.JIRA_EMAIL` | `JIRA_EMAIL` | — | LIVE mode for jira |
| `mcp_servers.jira.env.JIRA_API_TOKEN` | `JIRA_API_TOKEN` | — | LIVE mode for jira |
| `mcp_servers.aws-ecs.env.AWS_ACCESS_KEY_ID` | `AWS_ACCESS_KEY_ID` | — | LIVE mode for aws-ecs |
| `mcp_servers.aws-ecs.env.AWS_SECRET_ACCESS_KEY` | `AWS_SECRET_ACCESS_KEY` | — | LIVE mode for aws-ecs |
| `mcp_servers.aws-ecs.env.AWS_REGION` | `AWS_REGION` | `us-east-1` | LIVE mode for aws-ecs |
| `mcp_servers.postgres-db.env.DATABASE_URL` | `DATABASE_URL` | — | LIVE mode for postgres |

### 5.3 Validation Rules

| Rule | Enforced By | Failure Behavior |
|---|---|---|
| `execution_mode` ∈ {mock, live, mixed} | Pydantic enum | Startup failure with validation error |
| `llm.api_key` non-empty when mode != mock | Startup check | Warning logged; planning falls back to regex-only |
| `database.url` valid asyncpg URL | Pydantic URL validator | Startup failure |
| `cache.url` valid Redis URL | Pydantic URL validator | Startup failure |
| MCP server `mode` ∈ {mock, live, local} | Pydantic enum | Startup failure |
| MCP server `transport` ∈ {stdio, sse} | Pydantic enum | Startup failure |
| stdio transport requires `command` list | Pydantic validator | Startup failure |
| sse transport requires `url` string | Pydantic validator | Startup failure |
| `timeout` positive integer | Field(ge=1) | Validation error |
| `api_key` != default in production | Startup warning | Logged security warning |
| `admin_api_token` != default in production | Startup warning | Logged security warning |

### 5.4 Per-Server Mode Override Resolution

```python
# Pseudocode for mode resolution at tool call time
def resolve_execution_mode(
    global_mode: ExecutionMode,
    server_config: MCPSettings,
    server_name: str,
    request_override: ExecutionMode | None = None,
) -> Literal["mock", "live", "local"]:
    """[FR-29, FR-32] Resolve execution mode for a single tool call.

    Priority: per-call override > server config > global default
    """
    if request_override:
        return request_override.value

    server_mode = server_config.mode
    if server_mode != "mock":  # Server has explicit override
        return server_mode

    # Fall back to global mode
    if global_mode == ExecutionMode.MIXED:
        # In mixed mode without per-server override, default to mock
        return "mock"
    elif global_mode == ExecutionMode.LIVE:
        return "live"
    else:
        return "mock"
```

### 5.5 Runtime Mode Switching

When `POST /admin/mode` is called:

1. Validate admin token
2. Check for active executions (reject if `force=False`)
3. Update `mcp_server_states` table with new mode per server
4. Emit audit log entry: `action="mode_switched"`
5. Return `ModeSwitchResponse`

In-flight executions continue with their original mode. Only new executions use the new mode.

---

## 6. Package Structure & Dependencies

### 6.1 Monorepo Layout

```
mcp-opsmate/
├── opsmate/                    # Backend Python package
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── opsmate/                # Source root
│       ├── __init__.py
│       ├── api/
│       ├── core/
│       ├── services/
│       ├── infra/
│       ├── mcp_servers/
│       └── templates/
│
├── opsmate-cli/                # CLI application
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── opsmate_cli/
│
├── opsmate-web/                # React frontend
│   ├── package.json
│   ├── Dockerfile
│   └── src/
│
├── docker-compose.yml
├── alembic/                    # Database migrations
├── tests/                      # Integration + E2E tests
├── monitoring/                 # Prometheus/Grafana config
└── docs/
```

### 6.2 Backend `pyproject.toml` (Poetry)

```toml
# opsmate/pyproject.toml
[tool.poetry]
name = "opsmate"
version = "1.0.0"
description = "Infrastructure Automation MCP Terminal — FastAPI backend"
authors = ["Jashwanth Nag Veepuri <jashwanth@example.com>"]
readme = "README.md"
packages = [{ include = "opsmate" }]

[tool.poetry.dependencies]
python = "^3.13"

# Web framework & server
fastapi = "^0.115.0"
uvicorn = { version = "^0.34.0", extras = ["standard"] }
python-multipart = "^0.0.20"  # For form parsing

# Validation & configuration
pydantic = "^2.10.0"
pydantic-settings = "^2.7.0"
email-validator = "^2.2.0"

# Database
sqlalchemy = { version = "^2.0.36", extras = ["asyncio"] }
asyncpg = "^0.30.0"
alembic = "^1.14.0"

# Cache & circuit breaker
redis = "^5.2.0"

# HTTP client
httpx = { version = "^0.28.0", extras = ["http2"] }
httpx-sse = "^0.4.0"           # SSE stream consumption

# LLM integration
openai = "^1.58.0"

# MCP protocol
mcp = "^1.6.0"                  # Official MCP Python SDK

# Observability
prometheus-client = "^0.21.0"   # /metrics endpoint
structlog = "^24.4.0"           # Structured JSON logging

# Async utilities
anyio = "^4.7.0"

# Data generation (mock mode)
faker = "^33.0.0"

# Date/time
python-dateutil = "^2.9.0"

# YAML config
pyyaml = "^6.0.2"

# Security
python-jose = { version = "^3.3.0", extras = ["cryptography"] }  # JWT if needed
bcrypt = "^4.2.0"

[tool.poetry.group.dev.dependencies]
# Testing
pytest = "^8.3.0"
pytest-asyncio = "^0.25.0"
pytest-cov = "^6.0.0"
pytest-xdist = "^3.6.0"         # Parallel test execution
pytest-timeout = "^2.3.0"       # Test timeouts
pytest-mock = "^3.14.0"
httpx = "^0.28.0"               # ASGI TestClient (same as main)
factory-boy = "^3.3.0"          # Test data factories
faker = "^33.0.0"               # Also used in tests

# Linting & formatting
ruff = "^0.9.0"
mypy = "^1.14.0"

# Type stubs
types-pyyaml = "^6.0.0"
types-python-dateutil = "^2.9.0"

# Pre-commit
pre-commit = "^4.0.0"

[tool.poetry.scripts]
opsmate-server = "opsmate.api.main:run"
opsmate-migrate = "alembic.config.main:main"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"

# ─── Tool Configurations ─────────────────────────────────────

[tool.ruff]
target-version = "py313"
line-length = 100
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM", "ASYNC"]
ignore = ["E501"]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.mypy]
python_version = "3.13"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
addopts = "-v --tb=short --strict-markers"
markers = [
    "unit: Unit tests (fast, no external deps)",
    "integration: Integration tests (require Docker services)",
    "e2e: End-to-end tests (full stack)",
    "contract: Schema contract tests",
    "slow: Slow tests (> 5s)",
]

[tool.coverage.run]
source = ["opsmate"]
omit = ["*/tests/*", "*/mcp_servers/*/mock.py"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
]
fail_under = 75
```

### 6.3 CLI `pyproject.toml` (Poetry)

```toml
# opsmate-cli/pyproject.toml
[tool.poetry]
name = "opsmate-cli"
version = "1.0.0"
description = "mcp-opsmate CLI client — Rich TUI"
authors = ["Jashwanth Nag Veepuri <jashwanth@example.com>"]
readme = "README.md"
packages = [{ include = "opsmate_cli" }]

[tool.poetry.dependencies]
python = "^3.13"

# CLI framework
typer = { version = "^0.15.0", extras = ["all"] }
click = "^8.1.0"                # Typer dependency

# Terminal UI
rich = { version = "^13.9.0", extras = ["jupyter"] }

# HTTP client
httpx = { version = "^0.28.0", extras = ["http2"] }
httpx-sse = "^0.4.0"

# Configuration
pyyaml = "^6.0.2"
pydantic = "^2.10.0"
pydantic-settings = "^2.7.0"

# Async
anyio = "^4.7.0"

# History & completion
prompt-toolkit = "^3.0.48"

[tool.poetry.group.dev.dependencies]
pytest = "^8.3.0"
pytest-asyncio = "^0.25.0"
pytest-cov = "^6.0.0"
ruff = "^0.9.0"
mypy = "^1.14.0"

[tool.poetry.scripts]
opsmate = "opsmate_cli.main:main"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"

[tool.ruff]
target-version = "py313"
line-length = 100

[tool.mypy]
python_version = "3.13"
disallow_untyped_defs = true
ignore_missing_imports = true
```

### 6.4 Web Frontend `package.json`

```json
{
  "name": "opsmate-web",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "lint": "eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0",
    "lint:fix": "eslint . --ext ts,tsx --fix",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest",
    "test:coverage": "vitest run --coverage"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^7.0.0",
    "axios": "^1.7.0",
    "zod": "^3.24.0",
    "@tanstack/react-query": "^5.62.0",
    "recharts": "^2.15.0",
    "reactflow": "^11.11.0",
    "@xyflow/react": "^12.0.0",
    "lucide-react": "^0.468.0",
    "class-variance-authority": "^0.7.0",
    "clsx": "^2.1.0",
    "tailwind-merge": "^2.6.0",
    "date-fns": "^4.1.0",
    "react-markdown": "^9.0.0",
    "remark-gfm": "^4.0.0",
    "prismjs": "^1.29.0",
    "zustand": "^5.0.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@types/prismjs": "^1.26.0",
    "@typescript-eslint/eslint-plugin": "^8.18.0",
    "@typescript-eslint/parser": "^8.18.0",
    "@vitejs/plugin-react": "^4.3.0",
    "autoprefixer": "^10.4.0",
    "eslint": "^9.17.0",
    "eslint-plugin-react-hooks": "^5.1.0",
    "eslint-plugin-react-refresh": "^0.4.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.7.0",
    "vite": "^6.0.0",
    "vitest": "^2.1.0",
    "@vitest/coverage-v8": "^2.1.0",
    "jsdom": "^25.0.0",
    "@testing-library/react": "^16.1.0",
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/user-event": "^14.5.0"
  }
}
```

### 6.5 Internal Package Dependency Graph

```
opsmate (backend)
  ├─ core/              → pydantic, pydantic-settings, python-dateutil
  ├─ services/          → core/, infra/, anyio
  ├─ infra/             → core/, sqlalchemy, redis, httpx, openai, mcp, faker
  ├─ api/               → core/, services/, infra/, fastapi, uvicorn, prometheus-client
  └─ mcp_servers/       → mcp, httpx, pydantic (independent processes)

opsmate-cli
  ├─ opsmate core models (via shared package or HTTP)
  ├─ typer, rich, httpx, httpx-sse
  └─ prompt-toolkit

opsmate-web
  ├─ react, react-dom, react-router-dom
  ├─ axios (HTTP), zod (validation)
  ├─ @xyflow/react (DAG viz), recharts (charts)
  ├─ @tanstack/react-query (server state)
  └─ tailwindcss, lucide-react, date-fns
```

### 6.6 Version Compatibility Matrix

| Package | Version | Python | Notes |
|---|---|---|---|
| Python | 3.13+ | — | Required for asyncio.TaskGroup, type parameter syntax |
| FastAPI | 0.115+ | 3.9+ | Native Pydantic v2, WebSocket support |
| SQLAlchemy | 2.0.36+ | 3.7+ | `Mapped[]` type annotation syntax |
| asyncpg | 0.30+ | 3.8+ | PostgreSQL 16 support |
| Pydantic | 2.10+ | 3.8+ | V2 model validation, JSON Schema |
| MCP SDK | 1.6+ | 3.10+ | Official Anthropic SDK |
| uvicorn | 0.34+ | 3.8+ | HTTP/2, WebSocket support |



---

## 7. Docker Compose Specification

### 7.1 Complete `docker-compose.yml`

```yaml
# ═══════════════════════════════════════════════════════════════
# mcp-opsmate — Docker Compose Stack
# Usage: docker compose up -d
# Profiles:
#   default:    api, web, postgres, redis, nginx
#   dev:        api (hot-reload), web (hot-reload), postgres, redis
#   monitoring: +prometheus, +grafana
# ═══════════════════════════════════════════════════════════════

x-backend-env: &backend-env
  OPS_MATE_APP__EXECUTION_MODE: ${EXECUTION_MODE:-mock}
  OPS_MATE_APP__AUTO_APPROVE: ${AUTO_APPROVE:-false}
  OPS_MATE_LLM__API_KEY: ${OPENAI_API_KEY:-}
  OPS_MATE_LLM__MODEL: ${LLM_MODEL:-gpt-4o}
  OPS_MATE_DATABASE__URL: postgresql+asyncpg://opsmate:opsmate@postgres:5432/opsmate
  OPS_MATE_CACHE__URL: redis://redis:6379/0
  OPS_MATE_API_KEY: ${API_KEY:-dev-api-key-change-in-production}
  OPS_MATE_ADMIN_API_TOKEN: ${ADMIN_API_TOKEN:-dev-admin-token-change-in-production}
  OPS_MATE_LOGGING__LEVEL: ${LOG_LEVEL:-INFO}
  OPS_MATE_LOGGING__FORMAT: json
  # Per-MCP-server credentials (only used in LIVE mode)
  TAVILY_API_KEY: ${TAVILY_API_KEY:-}
  GITHUB_PAT: ${GITHUB_PAT:-}
  SLACK_WEBHOOK_URL: ${SLACK_WEBHOOK_URL:-}
  JIRA_URL: ${JIRA_URL:-}
  JIRA_EMAIL: ${JIRA_EMAIL:-}
  JIRA_API_TOKEN: ${JIRA_API_TOKEN:-}
  AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:-}
  AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:-}
  AWS_REGION: ${AWS_REGION:-us-east-1}

services:
  # ─── PostgreSQL ──────────────────────────────────────────────
  postgres:
    image: postgres:16-alpine
    container_name: opsmate-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: opsmate
      POSTGRES_PASSWORD: opsmate
      POSTGRES_DB: opsmate
      PGDATA: /var/lib/postgresql/data/pgdata
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./opsmate/alembic:/docker-entrypoint-initdb.d/alembic:ro
    ports:
      - "127.0.0.1:5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U opsmate -d opsmate"]
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 10s
    networks:
      - opsmate

  # ─── Redis ───────────────────────────────────────────────────
  redis:
    image: redis:7-alpine
    container_name: opsmate-redis
    restart: unless-stopped
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    ports:
      - "127.0.0.1:6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 5s
    networks:
      - opsmate

  # ─── FastAPI Backend ─────────────────────────────────────────
  api:
    build:
      context: ./opsmate
      dockerfile: Dockerfile
      target: production
    container_name: opsmate-api
    restart: unless-stopped
    environment:
      <<: *backend-env
    ports:
      - "127.0.0.1:8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 30s
    networks:
      - opsmate

  # ─── FastAPI Backend (Dev Mode) ──────────────────────────────
  api-dev:
    profiles: ["dev"]
    build:
      context: ./opsmate
      dockerfile: Dockerfile
      target: development
    container_name: opsmate-api-dev
    restart: "no"
    environment:
      <<: *backend-env
      UVICORN_RELOAD: "true"
      UVICORN_LOG_LEVEL: debug
    volumes:
      - ./opsmate/opsmate:/app/opsmate:ro  # Hot reload
      - ./opsmate/pyproject.toml:/app/pyproject.toml:ro
    ports:
      - "127.0.0.1:8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: >
      uvicorn opsmate.api.main:app
      --host 0.0.0.0
      --port 8000
      --reload
      --log-level debug
      --proxy-headers
    networks:
      - opsmate

  # ─── React Frontend ──────────────────────────────────────────
  web:
    build:
      context: ./opsmate-web
      dockerfile: Dockerfile
      target: production
    container_name: opsmate-web
    restart: unless-stopped
    ports:
      - "127.0.0.1:3000:80"
    depends_on:
      - api
    networks:
      - opsmate

  # ─── React Frontend (Dev Mode) ───────────────────────────────
  web-dev:
    profiles: ["dev"]
    build:
      context: ./opsmate-web
      dockerfile: Dockerfile
      target: development
    container_name: opsmate-web-dev
    restart: "no"
    environment:
      VITE_API_BASE_URL: http://localhost:8000
      VITE_WS_URL: ws://localhost:8000
    volumes:
      - ./opsmate-web/src:/app/src:ro
      - ./opsmate-web/public:/app/public:ro
      - ./opsmate-web/index.html:/app/index.html:ro
      - ./opsmate-web/vite.config.ts:/app/vite.config.ts:ro
      - ./opsmate-web/tsconfig.json:/app/tsconfig.json:ro
      - ./opsmate-web/tsconfig.app.json:/app/tsconfig.app.json:ro
      - ./opsmate-web/tsconfig.node.json:/app/tsconfig.node.json:ro
      - ./opsmate-web/tailwind.config.js:/app/tailwind.config.js:ro
      - ./opsmate-web/postcss.config.js:/app/postcss.config.js:ro
    ports:
      - "127.0.0.1:5173:5173"
    command: >
      npm run dev -- --host 0.0.0.0 --port 5173
    networks:
      - opsmate

  # ─── Nginx Reverse Proxy ─────────────────────────────────────
  nginx:
    image: nginx:alpine
    container_name: opsmate-nginx
    restart: unless-stopped
    ports:
      - "80:80"
    volumes:
      - ./opsmate-web/dist:/usr/share/nginx/html:ro
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - api
      - web
    networks:
      - opsmate

  # ─── Prometheus (monitoring profile) ─────────────────────────
  prometheus:
    profiles: ["monitoring"]
    image: prom/prometheus:latest
    container_name: opsmate-prometheus
    restart: unless-stopped
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./monitoring/alerts.yml:/etc/prometheus/alerts.yml:ro
      - prometheus_data:/prometheus
    ports:
      - "127.0.0.1:9090:9090"
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'
      - '--web.enable-lifecycle'
    networks:
      - opsmate

  # ─── Grafana (monitoring profile) ────────────────────────────
  grafana:
    profiles: ["monitoring"]
    image: grafana/grafana:latest
    container_name: opsmate-grafana
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD:-admin}
      GF_USERS_ALLOW_SIGN_UP: "false"
    volumes:
      - ./monitoring/grafana-dashboard.json:/var/lib/grafana/dashboards/opsmate.json:ro
      - grafana_data:/var/lib/grafana
    ports:
      - "127.0.0.1:3000:3000"
    networks:
      - opsmate

  # ─── CLI (interactive, one-off) ──────────────────────────────
  cli:
    profiles: ["cli"]
    build:
      context: ./opsmate-cli
      dockerfile: Dockerfile
    container_name: opsmate-cli
    restart: "no"
    environment:
      OPSMATE_API_URL: http://api:8000
      OPSMATE_API_KEY: ${API_KEY:-dev-api-key-change-in-production}
    stdin_open: true
    tty: true
    depends_on:
      - api
    networks:
      - opsmate
    command: ["opsmate", "interactive"]

volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local
  prometheus_data:
    driver: local
  grafana_data:
    driver: local

networks:
  opsmate:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

### 7.2 Backend Dockerfile

```dockerfile
# opsmate/Dockerfile
# ═══════════════════════════════════════════════════════════════
# Multi-stage build for FastAPI backend
# Targets: development, production
# ═══════════════════════════════════════════════════════════════

FROM python:3.13-slim AS base

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --no-cache-dir poetry==1.8.5

# Configure Poetry
RUN poetry config virtualenvs.create false

WORKDIR /app

# ─── Development Stage ─────────────────────────────────────────
FROM base AS development

COPY pyproject.toml poetry.lock* ./
RUN poetry install --with dev --no-interaction --no-ansi

COPY opsmate ./opsmate

EXPOSE 8000

CMD ["uvicorn", "opsmate.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ─── Production Stage ──────────────────────────────────────────
FROM base AS production

COPY pyproject.toml poetry.lock* ./
RUN poetry install --without dev --no-interaction --no-ansi --no-root

COPY opsmate ./opsmate

# Run as non-root user
RUN groupadd -r opsmate && useradd -r -g opsmate opsmate
RUN chown -R opsmate:opsmate /app
USER opsmate

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "opsmate.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

### 7.3 Frontend Dockerfile

```dockerfile
# opsmate-web/Dockerfile
# ═══════════════════════════════════════════════════════════════
# Multi-stage build for React frontend
# Targets: development, production
# ═══════════════════════════════════════════════════════════════

FROM node:22-alpine AS base
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

# ─── Development Stage ─────────────────────────────────────────
FROM base AS development
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ─── Build Stage ───────────────────────────────────────────────
FROM base AS build
COPY . .
RUN npm run build

# ─── Production Stage ──────────────────────────────────────────
FROM nginx:alpine AS production
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### 7.4 Nginx Configuration

```nginx
# nginx.conf — Reverse proxy for opsmate
server {
    listen 80;
    server_name localhost;

    # Frontend
    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # API
    location /api/ {
        proxy_pass http://api:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 30s;
        proxy_send_timeout 30s;
        proxy_read_timeout 60s;
    }

    # WebSocket
    location /ws/ {
        proxy_pass http://api:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    # SSE
    location /stream/ {
        proxy_pass http://api:8000/stream/;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }

    # Health (direct to API)
    location /health {
        proxy_pass http://api:8000/health;
    }

    # Metrics (direct to API)
    location /metrics {
        proxy_pass http://api:8000/metrics;
    }
}
```

### 7.5 `.env.example` File

```bash
# ═══════════════════════════════════════════════════════════════
# mcp-opsmate Environment Configuration
# Copy to .env and fill in your values
# ═══════════════════════════════════════════════════════════════

# ─── Core ──────────────────────────────────────────────────────
EXECUTION_MODE=mock                    # mock | live | mixed
API_KEY=change-me-in-production
ADMIN_API_TOKEN=change-me-in-production
LOG_LEVEL=INFO

# ─── LLM ───────────────────────────────────────────────────────
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o

# ─── External APIs (only needed for LIVE mode) ─────────────────
TAVILY_API_KEY=tvly-...
GITHUB_PAT=ghp_...
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
JIRA_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=...
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1

# ─── Database & Cache (Docker defaults work out of box) ────────
DATABASE_URL=postgresql+asyncpg://opsmate:opsmate@localhost:5432/opsmate
REDIS_URL=redis://localhost:6379/0

# ─── Monitoring ────────────────────────────────────────────────
GRAFANA_USER=admin
GRAFANA_PASSWORD=admin
```

### 7.6 Service Health Dependency Chain

```
Startup Order:
  1. postgres (wait for pg_isready)
  2. redis (wait for redis-cli ping)
  3. api (wait for /health 200)
  4. web (wait for api health)
  5. nginx (wait for api + web)

  [cli] → depends on api
  [prometheus] → depends on api (scrape target)
  [grafana] → depends on prometheus
```

### 7.7 Makefile (Common Commands)

```makefile
# Makefile — Common development commands
.PHONY: help install dev test lint format migrate build clean

help:
	@echo "mcp-opsmate Development Commands"
	@echo "  make dev         - Start dev stack (hot reload)"
	@echo "  make up          - Start production stack"
	@echo "  make down        - Stop all services"
	@echo "  make test        - Run all tests"
	@echo "  make test-unit   - Run unit tests only"
	@echo "  make test-int    - Run integration tests"
	@echo "  make lint        - Run ruff + mypy"
	@echo "  make format      - Auto-format code"
	@echo "  make migrate     - Run database migrations"
	@echo "  make migrate-gen - Generate new migration"
	@echo "  make build       - Build all Docker images"
	@echo "  make clean       - Remove containers + volumes"

dev:
	docker compose --profile dev up -d

up:
	docker compose up -d

down:
	docker compose --profile dev --profile monitoring --profile cli down

test:
	cd opsmate && poetry run pytest ../tests -v --cov=opsmate --cov-report=term-missing

test-unit:
	cd opsmate && poetry run pytest ../tests -v -m unit --cov=opsmate

test-int:
	cd opsmate && poetry run pytest ../tests -v -m integration

lint:
	cd opsmate && poetry run ruff check .
	cd opsmate && poetry run mypy opsmate/
	cd opsmate-cli && poetry run ruff check .

format:
	cd opsmate && poetry run ruff check . --fix
	cd opsmate && poetry run ruff format .
	cd opsmate-cli && poetry run ruff check . --fix
	cd opsmate-cli && poetry run ruff format .

migrate:
	cd opsmate && poetry run alembic upgrade head

migrate-gen:
	cd opsmate && poetry run alembic revision --autogenerate -m "$(msg)"

build:
	docker compose build

clean:
	docker compose down -v --remove-orphans
	docker system prune -f
```

---

## 8. Additional Technical Decisions

### 8.1 SQLAlchemy 2.0 Async Pattern vs. Sync

**Decision:** Use SQLAlchemy 2.0 async pattern exclusively (`asyncpg` driver, `AsyncSession`, `await` all queries).

**Rationale:**
- The orchestrator is built on `asyncio` (ADR-002); sync database calls would block the event loop
- `asyncpg` is the fastest PostgreSQL driver for Python (3-5x faster than psycopg2 for simple queries)
- SQLAlchemy 2.0's `Mapped[]` type annotations provide full type safety
- Single `AsyncEngine` shared across the application via FastAPI dependency injection

**Pattern:**

```python
# infra/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

engine = create_async_engine(
    settings.database.url,
    pool_size=settings.database.pool_size,
    max_overflow=settings.database.max_overflow,
    echo=settings.database.echo,
    pool_pre_ping=True,  # Verify connections before use
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# FastAPI dependency
async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session

# Usage in routes
@router.get("/executions/{id}")
async def get_execution(
    execution_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> ExecutionDetailResponse:
    result = await session.execute(
        select(Execution)
        .where(Execution.execution_id == execution_id)
        .options(selectinload(Execution.step_results))
    )
    execution = result.scalar_one_or_none()
    ...
```

**Trade-off:** Alembic migrations run synchronously. Use `run_async` wrapper or synchronous engine for migration scripts.

### 8.2 httpx vs. aiohttp for HTTP Client

**Decision:** Use `httpx` for all HTTP client needs.

| Criterion | httpx | aiohttp | Winner |
|---|---|---|---|
| MCP SDK compatibility | Official `mcp` SDK uses httpx | Requires adapter | httpx |
| SSE support | `httpx-sse` package, clean API | Manual implementation | httpx |
| API consistency | Sync + async in one package | Async only | httpx |
| TestClient | Built-in ASGI TestClient | Requires separate test setup | httpx |
| Connection pooling | HTTP/2 support, connection pooling | More mature pooling | Tie |

```python
# infra/llm.py — Shared httpx client
import httpx
from contextlib import asynccontextmanager

_http_client: httpx.AsyncClient | None = None

async def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _http_client

async def close_http_client() -> None:
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None
```

### 8.3 Redis Usage Patterns

Redis serves two distinct purposes with different data patterns:

| Purpose | Key Pattern | Value Type | TTL | Rationale |
|---|---|---|---|---|
| **Circuit Breaker State** | `cb:{server_name}` | String: `closed`/`half_open`/`open` | 30s | Auto-recovery after timeout; transient state |
| **Circuit Breaker Failures** | `cb:{server_name}:failures` | Integer (counter) | 30s | Tracks consecutive failures |
| **Tool Schema Cache** | `tools:{server_name}` | JSON (tool list) | 1h | Avoid re-discovery on reconnection |
| **Execution Rate Limit** | `ratelimit:{api_key_hash}` | Integer (count) | 1m | Optional per-key rate limiting |
| **WebSocket Presence** | `ws:{execution_id}` | Set (connection IDs) | 1h | Track active WS subscribers |

```python
# infra/cache.py — Redis client wrapper
import redis.asyncio as redis

_redis_pool: redis.Redis | None = None

async def get_redis() -> redis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(
            settings.cache.url,
            decode_responses=True,
            max_connections=20,
        )
    return _redis_pool

# Circuit breaker operations
async def get_circuit_state(server_name: str) -> CircuitState:
    r = await get_redis()
    state = await r.get(f"cb:{server_name}")
    return CircuitState(state) if state else CircuitState.CLOSED

async def set_circuit_state(server_name: str, state: CircuitState) -> None:
    r = await get_redis()
    await r.setex(f"cb:{server_name}", settings.cache.circuit_breaker_ttl, state.value)

async def record_failure(server_name: str) -> int:
    r = await get_redis()
    count = await r.incr(f"cb:{server_name}:failures")
    await r.expire(f"cb:{server_name}:failures", settings.cache.circuit_breaker_ttl)
    return int(count)

async def record_success(server_name: str) -> None:
    r = await get_redis()
    pipe = r.pipeline()
    pipe.setex(f"cb:{server_name}", settings.cache.circuit_breaker_ttl, CircuitState.CLOSED.value)
    pipe.delete(f"cb:{server_name}:failures")
    await pipe.execute()
```

### 8.4 OpenAI Function Calling vs. JSON Mode for Planning

**Decision:** Use **OpenAI Function Calling** for plan generation, with **JSON mode** as fallback.

| Criterion | Function Calling | JSON Mode | Decision |
|---|---|---|---|
| Schema enforcement | Native JSON Schema validation | Prompt-level only | Function Calling |
| Error handling | Structured refusal detection | Parse errors | Function Calling |
| Retry logic | Re-invoke with corrected schema | Regenerate full response | Function Calling |
| Tool descriptions | Native tool description support | Manual in prompt | Function Calling |
| Cost | Same token pricing | Same token pricing | Tie |

**Implementation:**

```python
# services/intent.py — Plan generation via function calling
from openai import AsyncOpenAI

PLAN_GENERATION_TOOLS = [{
    "type": "function",
    "function": {
        "name": "generate_execution_plan",
        "description": "Generate an execution plan DAG for the given intent",
        "parameters": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Unique step ID"},
                            "tool_name": {"type": "string", "description": "MCP tool to call"},
                            "server": {"type": "string", "description": "MCP server name"},
                            "description": {"type": "string"},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                            "critical": {"type": "boolean", "default": False},
                            "condition": {"type": ["string", "null"]},
                        },
                        "required": ["id", "tool_name", "server", "description"],
                    },
                },
                "explanation": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["steps", "explanation", "confidence"],
        },
    },
}]

async def generate_plan(
    client: AsyncOpenAI,
    intent: IntentClassification,
    available_tools: list[ToolInfo],
) -> ExecutionPlan:
    """Generate execution plan using function calling."""
    response = await client.chat.completions.create(
        model="gpt-4o",
        temperature=0.2,
        tools=PLAN_GENERATION_TOOLS,
        tool_choice={"type": "function", "function": {"name": "generate_execution_plan"}},
        messages=[
            {
                "role": "system",
                "content": f"You are an infrastructure automation planner. Available tools:\n{format_tools(available_tools)}",
            },
            {
                "role": "user",
                "content": f"Command: {intent.command_summary}\nEntities: {intent.entities}",
            },
        ],
    )

    if response.choices[0].message.tool_calls:
        args = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
        return ExecutionPlan.model_validate(args)
    else:
        # Fallback: parse content as JSON
        content = response.choices[0].message.content
        return ExecutionPlan.model_validate_json(content)
```

### 8.5 Pydantic v2 Discriminated Unions for Step Results

Step results can have different output shapes depending on the tool. Using discriminated unions provides type-safe access:

```python
# core/models.py — Discriminated union for typed step outputs
from pydantic import Field
from typing import Annotated, Literal

class PodDescribeResult(BaseModel):
    result_type: Literal["pod_describe"] = "pod_describe"
    pods: list[PodStatus]
    total_pods: int

class MetricResult(BaseModel):
    result_type: Literal["metrics"] = "metrics"
    metric: str
    datapoints: list[MetricDatapoint]
    statistics: dict[str, float]

class GenericResult(BaseModel):
    result_type: Literal["generic"] = "generic"
    data: dict[str, Any]

# Discriminated union
StepOutput = Annotated[
    PodDescribeResult | MetricResult | GenericResult,
    Field(discriminator="result_type"),
]

# In StepResult:
class TypedStepResult(StepResult):
    """Step result with typed output based on tool category."""
    typed_output: StepOutput | None = None
```

**Benefits:**
- Type-safe access to tool-specific fields in downstream steps
- Automatic validation of output shape per tool category
- Clear error messages when output doesn't match expected schema



---

## 9. Testing Strategy Details

### 9.1 Test Configuration

```ini
# pytest.ini (embedded in pyproject.toml)
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
addopts = "-v --tb=short --strict-markers --cov=opsmate --cov-report=term-missing --cov-report=xml"
markers = [
    "unit: Fast unit tests, no external dependencies",
    "integration: Requires Docker services (postgres, redis)",
    "e2e: Full end-to-end stack tests",
    "contract: Schema parity between mock and live",
    "slow: Tests that take > 5 seconds",
]
filterwarnings = [
    "ignore::DeprecationWarning",
]
```

### 9.2 Test Fixtures (`conftest.py`)

```python
# tests/conftest.py — Shared test fixtures
import asyncio
import os
import uuid
from datetime import datetime
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from opsmate.api.main import create_app
from opsmate.core.config import OpsMateConfig
from opsmate.core.models import (
    ExecutionPlan, PlanStep, ExecutionState, ExecutionStatus,
    StepResult, StepStatus, ExecutionContext, StepError, ErrorType,
    IntentClassification, IntentType,
)
from infra.database import Base, get_db_session


# ─── Event Loop ─────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ─── Test Database ──────────────────────────────────────────────

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://opsmate:opsmate@localhost:5432/opsmate_test"
)

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    echo=False,
)

TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_database() -> AsyncIterator[None]:
    """Create all tables before tests, drop after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Provide a fresh database session for each test."""
    async with TestSessionLocal() as session:
        yield session
        # Rollback any uncommitted changes
        await session.rollback()


# ─── FastAPI Test Client ────────────────────────────────────────

@pytest_asyncio.fixture
async def test_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """HTTP test client with overridden database dependency."""
    app = create_app(config=OpsMateConfig(
        app={"execution_mode": "mock"},
        database={"url": TEST_DATABASE_URL},
    ))

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "test-api-key"},
    ) as client:
        yield client

    app.dependency_overrides.clear()


# ─── Mock MCP Server Fixture ────────────────────────────────────

class MockMCPServer:
    """In-memory mock MCP server for testing."""

    def __init__(self, name: str, tools: dict[str, callable]):
        self.name = name
        self.tools = tools
        self.call_log: list[dict] = []

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        if tool_name not in self.tools:
            raise ValueError(f"Tool '{tool_name}' not found on server '{self.name}'")
        self.call_log.append({"tool": tool_name, "args": arguments})
        return await self.tools[tool_name](**arguments)


@pytest.fixture
def mock_mcp_hub():
    """Provide a mock MCP hub with pre-configured mock servers."""
    from opsmate.infra.mcp_hub import MCPHub

    hub = MCPHub()

    # Register mock servers
    hub.register_server(MockMCPServer("aws-ecs", {
        "describe_pods": lambda **kw: {
            "pods": [
                {"name": "pod-1", "namespace": kw.get("namespace"), "status": "Running",
                 "restarts": 0, "cpu_percent": 45.0, "memory_percent": 60.0, "age": "2h"},
                {"name": "pod-2", "namespace": kw.get("namespace"), "status": "Running",
                 "restarts": 1, "cpu_percent": 78.5, "memory_percent": 72.0, "age": "5h"},
            ],
            "namespace": kw.get("namespace"),
            "service": kw.get("service"),
            "total_pods": 2,
        },
        "get_metrics": lambda **kw: {
            "metric": kw.get("metric"),
            "datapoints": [{"timestamp": f"2025-01-01T{i:02d}:00:00Z", "value": 40.0 + i * 2, "unit": "Percent"}
                          for i in range(24)],
            "statistics": {"avg": 55.0, "min": 40.0, "max": 86.0, "p99": 84.0},
        },
        "restart_pod": lambda **kw: {
            "pod_name": kw.get("pod_name"),
            "namespace": kw.get("namespace"),
            "previous_status": "Running",
            "restart_initiated": True,
            "message": f"Pod {kw.get('pod_name')} restarted",
        },
    }))

    hub.register_server(MockMCPServer("slack", {
        "send_message": lambda **kw: {
            "ok": True,
            "channel": kw.get("channel"),
            "ts": "1234567890.123456",
            "delivery_status": "delivered",
        },
    }))

    hub.register_server(MockMCPServer("calculator", {
        "math": lambda **kw: {"result": eval(kw.get("expression", "0")), "expression": kw.get("expression")},
        "threshold_check": lambda **kw: {
            "triggered": eval(f"{kw.get('value')} {kw.get('operator')} {kw.get('threshold')}"),
            "value": kw.get("value"),
            "operator": kw.get("operator"),
            "threshold": kw.get("threshold"),
            "message": f"Check: {kw.get('value')} {kw.get('operator')} {kw.get('threshold')}",
        },
    }))

    return hub


# ─── Factory Fixtures ───────────────────────────────────────────

@pytest.fixture
def sample_execution_plan() -> ExecutionPlan:
    """Create a sample 4-step execution plan."""
    return ExecutionPlan(
        template_used="health-check-and-remediate",
        steps=[
            PlanStep(
                id="step-1",
                tool_name="describe_pods",
                server="aws-ecs",
                description="Get pod status for payment-service",
                output_schema={"pods": "list[PodStatus]"},
                critical=False,
            ),
            PlanStep(
                id="step-2",
                tool_name="get_metrics",
                server="aws-ecs",
                description="Get CPU metrics for payment-service",
                input_mapping={"namespace": "{{context.namespace}}", "service": "{{context.service}}", "metric": "cpu"},
                depends_on=["step-1"],
                critical=False,
            ),
            PlanStep(
                id="step-3",
                tool_name="threshold_check",
                server="calculator",
                description="Check if CPU > 80%",
                input_mapping={"value": "{{step-2.statistics.avg}}", "operator": ">", "threshold": "80"},
                depends_on=["step-2"],
                condition="{{step-2.statistics.avg}} > 80",
                critical=False,
            ),
            PlanStep(
                id="step-4",
                tool_name="send_message",
                server="slack",
                description="Alert on-call channel",
                input_mapping={"channel": "#on-call", "text": "CPU alert: {{step-2.statistics.avg}}%"},
                depends_on=["step-3"],
                critical=False,
            ),
        ],
        dependencies={
            "step-1": ["step-2"],
            "step-2": ["step-3"],
            "step-3": ["step-4"],
        },
        estimated_duration_ms=5000,
        confidence=0.92,
    )


@pytest.fixture
def sample_execution_state(sample_execution_plan: ExecutionPlan) -> ExecutionState:
    """Create a sample execution in EXECUTING state."""
    return ExecutionState(
        execution_id=uuid.uuid4(),
        status=ExecutionStatus.EXECUTING,
        command_text="Check payment-service health and alert if CPU > 80%",
        execution_mode="mock",
        plan=sample_execution_plan,
        context=ExecutionContext(
            variables={"namespace": "production", "service": "payment-service"},
            metadata={"user_id": "test-user"},
        ),
    )


@pytest.fixture
def sample_intent() -> IntentClassification:
    """Create a sample intent classification."""
    return IntentClassification(
        intent_types=[IntentType.QUERY, IntentType.ACTION, IntentType.NOTIFY],
        entities=[
            {"type": "service_name", "value": "payment-service", "raw_text": "payment-service", "confidence": 0.95, "resolved": True},
            {"type": "threshold", "value": 80.0, "raw_text": "80%", "confidence": 0.99, "resolved": True},
            {"type": "channel", "value": "#on-call", "raw_text": "on-call channel", "confidence": 0.88, "resolved": True},
        ],
        confidence=0.92,
        command_summary="Check payment-service pod health and CPU, restart if needed, alert on-call",
        requires_clarification=False,
    )
```

### 9.3 Test Categories & Examples

#### Unit Tests (`-m unit`)

```python
# tests/test_services/test_executor.py
import pytest
from opsmate.services.executor import StepExecutor
from opsmate.core.models import StepStatus, ErrorType

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class TestStepExecutor:
    """Unit tests for the step executor (no external deps)."""

    async def test_execute_single_step_success(self, sample_execution_state, mock_mcp_hub):
        """A single non-critical step executes successfully."""
        executor = StepExecutor(hub=mock_mcp_hub)
        step = sample_execution_state.plan.steps[0]

        result = await executor.execute_step(
            step=step,
            context=sample_execution_state.context,
            execution_mode="mock",
        )

        assert result.status == StepStatus.COMPLETED
        assert result.step_id == "step-1"
        assert result.output is not None
        assert result.error is None
        assert result.duration_ms is not None
        assert result.duration_ms > 0

    async def test_execute_step_circuit_breaker_open(self, sample_execution_state, mock_mcp_hub, mocker):
        """Step fails fast when circuit breaker is OPEN."""
        executor = StepExecutor(hub=mock_mcp_hub)
        step = sample_execution_state.plan.steps[0]

        # Mock circuit breaker as OPEN
        mocker.patch.object(
            executor.circuit_breaker, "get_state",
            return_value="open"
        )

        result = await executor.execute_step(
            step=step,
            context=sample_execution_state.context,
            execution_mode="mock",
        )

        assert result.status == StepStatus.FAILED
        assert result.error is not None
        assert result.error.classification == ErrorType.TRANSIENT
        assert "circuit" in result.error.message.lower()

    async def test_conditional_step_skipped(self, sample_execution_state, mock_mcp_hub, mocker):
        """Step with condition evaluates to false → SKIPPED."""
        executor = StepExecutor(hub=mock_mcp_hub)
        step = sample_execution_state.plan.steps[2]  # step-3 with condition

        # Mock condition evaluation: CPU 45% < 80 → skip
        mocker.patch.object(
            executor, "evaluate_condition",
            return_value=False
        )

        result = await executor.execute_step(
            step=step,
            context=sample_execution_state.context,
            execution_mode="mock",
        )

        assert result.status == StepStatus.SKIPPED

    async def test_critical_step_failure_halts(self, sample_execution_state, mock_mcp_hub, mocker):
        """Critical step failure raises CriticalStepFailure."""
        executor = StepExecutor(hub=mock_mcp_hub)
        step = sample_execution_state.plan.steps[0]
        step.critical = True

        # Mock tool call to raise exception
        mocker.patch.object(
            mock_mcp_hub, "call_tool",
            side_effect=ConnectionError("Connection refused")
        )

        with pytest.raises(CriticalStepFailure):
            await executor.execute_step(
                step=step,
                context=sample_execution_state.context,
                execution_mode="mock",
            )

    async def test_retry_exhaustion(self, sample_execution_state, mock_mcp_hub, mocker):
        """After 3 retries, step is marked FAILED."""
        executor = StepExecutor(hub=mock_mcp_hub)
        step = sample_execution_state.plan.steps[0]

        # Mock tool to always fail with transient error
        mocker.patch.object(
            mock_mcp_hub, "call_tool",
            side_effect=TimeoutError("Connection timeout")
        )

        result = await executor.execute_step(
            step=step,
            context=sample_execution_state.context,
            execution_mode="mock",
        )

        assert result.status == StepStatus.FAILED
        assert result.attempt_count == 3
        assert result.error.retryable is True
        assert result.error.attempt_count == 3
```

#### Integration Tests (`-m integration`)

```python
# tests/test_api/test_commands.py
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class TestCommandsEndpoint:
    """Integration tests for POST /commands (requires postgres + api)."""

    async def test_submit_command(self, test_client):
        """[FR-01] Submit a command and get execution ID."""
        response = await test_client.post(
            "/commands",
            json={"text": "Check payment-service pods in production"},
        )

        assert response.status_code == 202
        data = response.json()
        assert "execution_id" in data
        assert data["status"] == "pending"
        assert "stream_url" in data

    async def test_command_validation_empty(self, test_client):
        """[FR-01] Empty command returns 400."""
        response = await test_client.post(
            "/commands",
            json={"text": ""},
        )
        assert response.status_code == 422

    async def test_command_too_long(self, test_client):
        """[FR-01] Command > 2000 chars returns 400."""
        response = await test_client.post(
            "/commands",
            json={"text": "x" * 2001},
        )
        assert response.status_code == 422

    async def test_missing_api_key(self, test_client):
        """[NFR-11] Request without API key returns 401."""
        response = await test_client.post(
            "/commands",
            json={"text": "Check pods"},
            headers={},  # No X-API-Key
        )
        assert response.status_code == 401

    async def test_execution_persistence(self, test_client, db_session):
        """[FR-21] Execution state is persisted to PostgreSQL."""
        response = await test_client.post(
            "/commands",
            json={"text": "List all running pods"},
        )
        data = response.json()
        execution_id = data["execution_id"]

        # Query database directly
        from opsmate.infra.database import Execution
        result = await db_session.execute(
            select(Execution).where(Execution.execution_id == execution_id)
        )
        execution = result.scalar_one()
        assert execution.command_text == "List all running pods"
        assert execution.status == "pending"

    async def test_mode_in_response(self, test_client):
        """[FR-33] Execution mode indicated in response."""
        response = await test_client.post(
            "/commands",
            json={"text": "Check pods"},
        )
        data = response.json()
        assert "execution_mode" in data
        assert data["execution_mode"] == "mock"
```

#### Contract Tests (`-m contract`)

```python
# tests/test_contract/test_schema_parity.py
import pytest
from opsmate.mcp_servers.aws_ecs.mock import AWSECSMock
from opsmate.core.models import (
    AWSDescribePodsOutput, AWSGetMetricsOutput, AWSRestartPodOutput,
    GitHubRepoInfoOutput, GitHubWorkflowStatusOutput, GitHubPRChecksOutput,
    SlackSendMessageOutput, JiraSearchTicketsOutput, JiraCreateIncidentOutput,
    TavilySearchOutput, TavilyAnswerOutput,
    CalculatorMathOutput, CalculatorDateOutput, CalculatorThresholdOutput,
    PostgresExecuteQueryOutput,
)

pytestmark = pytest.mark.contract


class TestSchemaParity:
    """[NFR-23] Mock outputs validate against same schemas as live outputs."""

    @pytest.mark.asyncio
    async def test_aws_describe_pods_schema(self):
        mock = AWSECSMock(seed=42)
        result = await mock.describe_pods(namespace="prod", service="payment")
        validated = AWSDescribePodsOutput.model_validate(result)
        assert validated.total_pods == len(validated.pods)
        assert all(p.namespace == "prod" for p in validated.pods)

    @pytest.mark.asyncio
    async def test_aws_get_metrics_schema(self):
        mock = AWSECSMock(seed=42)
        result = await mock.get_metrics(namespace="prod", service="payment", metric="cpu")
        validated = AWSGetMetricsOutput.model_validate(result)
        assert validated.metric == "cpu"
        assert "avg" in validated.statistics
        assert "p99" in validated.statistics

    @pytest.mark.asyncio
    async def test_aws_restart_pod_schema(self):
        mock = AWSECSMock(seed=42)
        result = await mock.restart_pod(namespace="prod", pod_name="pod-1")
        validated = AWSRestartPodOutput.model_validate(result)
        assert validated.restart_initiated is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mock_class,method_name,input_kwargs,schema_class", [
        # Tavily
        (TavilyMock, "search", {"query": "kubernetes", "max_results": 5}, TavilySearchOutput),
        (TavilyMock, "answer", {"query": "What is Kubernetes?"}, TavilyAnswerOutput),
        # GitHub
        (GitHubMock, "repo_info", {"owner": "test-org", "repo": "test-repo"}, GitHubRepoInfoOutput),
        (GitHubMock, "workflow_status", {"owner": "test-org", "repo": "test-repo"}, GitHubWorkflowStatusOutput),
        (GitHubMock, "pr_checks", {"owner": "test-org", "repo": "test-repo", "pr_number": 42}, GitHubPRChecksOutput),
        # Slack
        (SlackMock, "send_message", {"channel": "#alerts", "text": "Test alert"}, SlackSendMessageOutput),
        # Jira
        (JiraMock, "search_tickets", {"jql": "project = OPS"}, JiraSearchTicketsOutput),
        (JiraMock, "create_incident", {"summary": "Test incident", "description": "Details"}, JiraCreateIncidentOutput),
        # Calculator
        (CalculatorServer, "math", {"expression": "2 + 2"}, CalculatorMathOutput),
        (CalculatorServer, "threshold_check", {"value": 85, "operator": ">", "threshold": 80}, CalculatorThresholdOutput),
        # Postgres
        (PostgresMock, "execute_query", {"sql": "SELECT * FROM test"}, PostgresExecuteQueryOutput),
    ])
    async def test_all_tool_schemas(self, mock_class, method_name, input_kwargs, schema_class):
        """All 7 MCP servers produce schema-valid output."""
        mock = mock_class(seed=42)
        method = getattr(mock, method_name)
        result = await method(**input_kwargs)
        validated = schema_class.model_validate(result)
        assert validated is not None
```

#### E2E Tests (`-m e2e`)

```python
# tests/test_e2e/test_full_flow.py
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.slow, pytest.mark.asyncio]


class TestFullExecutionFlow:
    """End-to-end tests for complete command → output flows."""

    async def test_health_check_and_remediate(self, test_client):
        """[US-1] Full flow: check pods → metrics → conditional restart → slack alert."""
        # Submit command
        response = await test_client.post("/commands", json={
            "text": "Check payment-service pods, show CPU for last 2h, restart if > 80%, alert #on-call",
            "auto_approve": True,
        })
        assert response.status_code == 202
        data = response.json()
        execution_id = data["execution_id"]

        # Poll for completion
        for _ in range(30):  # Max 30 seconds
            await asyncio.sleep(1)
            status_resp = await test_client.get(f"/executions/{execution_id}")
            status_data = status_resp.json()
            if status_data["status"] in ("completed", "failed"):
                break

        assert status_data["status"] == "completed"
        assert "step-1" in status_data["results"]  # describe_pods
        assert "step-2" in status_data["results"]  # get_metrics
        assert "step-3" in status_data["results"]  # threshold_check
        assert "step-4" in status_data["results"]  # send_message

    async def test_execution_mode_indicated(self, test_client):
        """[FR-33] Execution mode shown in every response."""
        response = await test_client.post("/commands", json={
            "text": "List running pods for api-gateway",
        })
        data = response.json()
        assert data["execution_mode"] == "mock"

        # Mode badge in execution detail
        detail = await test_client.get(f"/executions/{data['execution_id']}")
        detail_data = detail.json()
        assert detail_data["execution_mode"] == "mock"
```

### 9.4 Coverage Reporting

```python
# .coveragerc (embedded in pyproject.toml)
[tool.coverage.run]
source = ["opsmate"]
omit = [
    "*/tests/*",
    "*/test_*",
    "opsmate/mcp_servers/*/mock.py",  # Mock data generation
    "opsmate/api/main.py",             # App factory boilerplate
]
branch = true

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
    "pass",
]
show_missing = true
skip_empty = true
fail_under = 75

[tool.coverage.html]
directory = "htmlcov"
```

### 9.5 CI/CD Test Pipeline

```yaml
# .github/workflows/test.yml (pseudocode)
name: Test Pipeline
on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install poetry && poetry install --with dev
      - run: poetry run pytest tests -m unit -v --cov --cov-report=xml
      - uses: codecov/codecov-action@v4

  integration-tests:
    runs-on: ubuntu-latest
    services:
      postgres: { image: postgres:16, env: { POSTGRES_PASSWORD: opsmate } }
      redis: { image: redis:7 }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install poetry && poetry install --with dev
      - run: poetry run pytest tests -m integration -v --timeout=120

  contract-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install poetry && poetry install --with dev
      - run: poetry run pytest tests -m contract -v

  e2e-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker compose up -d
      - run: sleep 30  # Wait for services
      - run: docker compose exec api poetry run pytest tests -m e2e -v --timeout=300
      - run: docker compose down -v

  security-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install bandit semgrep
      - run: bandit -r opsmate/ -f json -o bandit-report.json
      - run: semgrep --config=auto opsmate/ --json -o semgrep-report.json
```

---

## 10. Implementation Order & Estimates

### 10.1 Phase 1: Foundation (Weeks 1–2)

| # | Task | Complexity | Files | Dependencies | Req. IDs |
|---|---|---|---|---|---|
| 1.1 | Set up monorepo structure, Poetry configs, Docker Compose skeleton | M | 15 | None | NFR-21 |
| 1.2 | Implement SQLAlchemy models + Alembic migration | M | 5 | 1.1 | FR-21 |
| 1.3 | Implement Pydantic core models (Command, Plan, State, Context, Error) | M | 2 | 1.1 | FR-06, FR-20 |
| 1.4 | Implement Pydantic-Settings configuration loader | S | 2 | 1.1 | FR-42, FR-43 |
| 1.5 | Set up PostgreSQL + Redis in Docker Compose with health checks | S | 2 | 1.1 | NFR-21 |
| 1.6 | Set up pytest + pytest-asyncio + test fixtures + factories | M | 4 | 1.2, 1.3 | NFR-23 |
| 1.7 | Unit tests for core models (Plan DAG validation, Error classification) | M | 3 | 1.3, 1.6 | FR-06 |

**Phase 1 Deliverable:** Backend skeleton with database, models, config, and passing unit tests.

### 10.2 Phase 2: MCP Server Hub (Weeks 2–3)

| # | Task | Complexity | Files | Dependencies | Req. IDs |
|---|---|---|---|---|---|
| 2.1 | Implement BaseMCPServer + stdio transport runner | M | 3 | 1.1 | FR-11 |
| 2.2 | Implement MCPHub (client manager, tool registry, mode router) | H | 4 | 2.1 | FR-11, FR-12 |
| 2.3 | Implement MockFactory with seeded faker + latency injection | M | 3 | 2.2 | FR-30 |
| 2.4 | Implement all 7 MCP servers (live + mock) | H | 21 | 2.1 | FR-11, NFR-23 |
| 2.5 | Implement circuit breaker (Redis-backed) | M | 2 | 2.2, 1.5 | FR-17 |
| 2.6 | Unit tests for MCPHub, circuit breaker, mock factory | M | 6 | 2.2, 2.5, 1.6 | FR-17 |
| 2.7 | Contract tests: mock/live schema parity for all 7 servers | M | 2 | 2.4, 1.6 | NFR-23 |

**Phase 2 Deliverable:** All MCP servers connectable in both MOCK and LIVE modes; tool discovery working; circuit breaker operational.

### 10.3 Phase 3: Orchestrator Engine (Weeks 3–5)

| # | Task | Complexity | Files | Dependencies | Req. IDs |
|---|---|---|---|---|---|
| 3.1 | Implement state machine with all transitions | M | 2 | 1.3 | FR-21, FR-22 |
| 3.2 | Implement StateManager (PostgreSQL persistence) | M | 2 | 1.2, 3.1 | FR-21, FR-22 |
| 3.3 | Implement Intent Classifier (regex + LLM hybrid) | H | 2 | 1.3 | FR-02, FR-03 |
| 3.4 | Implement Intent Planner (template + zero-shot) | H | 3 | 3.3, 2.2 | FR-06, FR-07 |
| 3.5 | Implement Step Executor (asyncio.TaskGroup + topological sort) | H | 2 | 3.2, 2.2 | FR-13, FR-14 |
| 3.6 | Implement Error Recovery Handler (retry + escalation) | H | 2 | 3.5, 2.5 | FR-16, FR-18, FR-19 |
| 3.7 | Implement audit logging (structured JSON) | M | 2 | 3.2 | FR-25, FR-26 |
| 3.8 | Implement conditional step execution | M | 1 | 3.5 | FR-15 |
| 3.9 | Integration tests for full execution flow | H | 8 | 3.1–3.8 | FR-06–FR-20 |

**Phase 3 Deliverable:** Complete command → plan → execute → persist pipeline working end-to-end in MOCK mode.

### 10.4 Phase 4: API Layer (Weeks 5–6)

| # | Task | Complexity | Files | Dependencies | Req. IDs |
|---|---|---|---|---|---|
| 4.1 | Implement FastAPI app factory + lifespan management | M | 2 | 1.1 | NFR-06 |
| 4.2 | Implement auth middleware (API key + admin token) | M | 2 | 4.1 | NFR-11, NFR-12 |
| 4.3 | Implement `POST /commands` endpoint | M | 1 | 3.3, 4.2 | FR-01 |
| 4.4 | Implement `GET /executions` + `GET /executions/{id}` endpoints | S | 1 | 3.2, 4.2 | FR-23 |
| 4.5 | Implement `POST /executions/{id}/approve` endpoint | S | 1 | 3.1, 4.2 | FR-09 |
| 4.6 | Implement SSE stream endpoint (`GET /stream/{id}`) | M | 1 | 3.5, 4.1 | FR-36 |
| 4.7 | Implement WebSocket handler | M | 1 | 3.5, 4.1 | FR-39 |
| 4.8 | Implement `/health` endpoint | S | 1 | 4.1 | FR-27 |
| 4.9 | Implement `/metrics` endpoint (Prometheus) | S | 1 | 4.1 | NFR-19 |
| 4.10 | Implement `/admin/*` endpoints (mode, tools) | M | 1 | 2.2, 4.2 | FR-32, FR-44 |
| 4.11 | Integration tests for all API endpoints | H | 6 | 4.1–4.10 | NFR-11 |

**Phase 4 Deliverable:** Full REST API + SSE + WebSocket operational; all endpoints tested.

### 10.5 Phase 5: CLI (Weeks 6–7)

| # | Task | Complexity | Files | Dependencies | Req. IDs |
|---|---|---|---|---|---|
| 5.1 | Set up opsmate-cli package (Typer + Rich) | S | 4 | 1.1 | FR-34 |
| 5.2 | Implement HTTP client for backend API | S | 1 | 5.1 | FR-36 |
| 5.3 | Implement SSE consumer with Rich rendering | M | 2 | 5.2 | FR-36 |
| 5.4 | Implement Rich components (plan panel, tables, spinners, mode badge) | M | 3 | 5.1 | FR-34 |
| 5.5 | Implement interactive mode with history and tab completion | M | 2 | 5.1 | FR-35 |
| 5.6 | Implement CLI flags (--mode, --auto-approve, --output, --verbose) | S | 1 | 5.1 | FR-37 |
| 5.7 | E2E tests for CLI flows (pexpect) | M | 4 | 5.1–5.6 | FR-34–FR-37 |

**Phase 5 Deliverable:** Working CLI with Rich TUI, streaming output, plan confirmation, and history.

### 10.6 Phase 6: Web UI (Weeks 7–9)

| # | Task | Complexity | Files | Dependencies | Req. IDs |
|---|---|---|---|---|---|
| 6.1 | Set up React + Vite + TypeScript + Tailwind project | S | 8 | 1.1 | FR-38 |
| 6.2 | Implement API client (Axios + Zod validation) | M | 4 | 6.1 | FR-38 |
| 6.3 | Implement auth context + mode context | S | 2 | 6.1 | FR-41 |
| 6.4 | Implement Chat page (message thread, input, markdown rendering) | M | 4 | 6.2, 6.3 | FR-38 |
| 6.5 | Implement Plan DAG visualization (ReactFlow) | H | 3 | 6.2 | FR-39 |
| 6.6 | Implement WebSocket hook for real-time updates | M | 1 | 6.1 | FR-39 |
| 6.7 | Implement Execution History page | M | 3 | 6.2 | FR-40 |
| 6.8 | Implement Dashboard page (metrics, charts) | M | 3 | 6.2 | FR-40 |
| 6.9 | Implement Admin page (mode switch, tool registry) | M | 2 | 6.2, 6.3 | FR-41 |
| 6.10 | Mode indicator + confirmation dialogs | S | 2 | 6.3 | FR-41 |
| 6.11 | E2E tests for Web UI (Playwright) | H | 6 | 6.1–6.10 | FR-38–FR-41 |

**Phase 6 Deliverable:** Complete React Web UI with chat, DAG visualization, history, dashboard, and admin controls.

### 10.7 Phase 7: Observability & Polish (Weeks 9–10)

| # | Task | Complexity | Files | Dependencies | Req. IDs |
|---|---|---|---|---|---|
| 7.1 | Configure structured JSON logging + secret redaction | M | 2 | 4.1 | FR-25, FR-26 |
| 7.2 | Set up Prometheus metrics collection | M | 2 | 4.1 | NFR-19 |
| 7.3 | Configure Prometheus + Grafana in Docker Compose | S | 3 | 7.2 | NFR-19 |
| 7.4 | Define alert rules (MCP disconnect, error rate, memory) | S | 1 | 7.2 | NFR-20 |
| 7.5 | SIGTERM graceful shutdown handler | M | 1 | 3.2 | FR-22 |
| 7.6 | Execution history archival (compress + delete old) | M | 2 | 3.2 | FR-24 |
| 7.7 | Performance testing + optimization | H | — | All | NFR-01–NFR-05 |
| 7.8 | Security audit (bandit, semgrep, secret scanning) | M | — | All | NFR-10–NFR-13 |
| 7.9 | Documentation (API docs, deployment guide, dev setup) | M | 6 | All | — |
| 7.10 | Final integration testing + bug fixes | H | — | All | All |

**Phase 7 Deliverable:** Production-ready system with observability, graceful shutdown, archival, documentation, and passing all NFR targets.

### 10.8 Summary Timeline

```
Week  1: Phase 1  ████████████████████████████████████████ Foundation
Week  2: Phase 1+2 ██████████████████████████████████████ MCP Hub
Week  3: Phase 2+3 ██████████████████████████████████████ MCP Hub + Orchestrator
Week  4: Phase 3   ██████████████████████████████████████ Orchestrator
Week  5: Phase 3   ██████████████████████████████████████ Orchestrator
Week  6: Phase 4+5 ██████████████████████████████████████ API + CLI
Week  7: Phase 5   ██████████████████████████████████████ CLI
Week  8: Phase 6   ██████████████████████████████████████ Web UI
Week  9: Phase 6   ██████████████████████████████████████ Web UI
Week 10: Phase 7   ██████████████████████████████████████ Observability + Polish
```

**Total estimated effort:** 10 weeks (1 engineer) or 5 weeks (2 engineers with parallel frontend/backend work).

### 10.9 Risk Factors

| Risk | Mitigation |
|---|---|
| LLM planning latency > 5s | Add template matching cache; implement regex-only fallback |
| MCP SDK breaking changes | Pin `mcp` version; abstract behind internal wrapper |
| PostgreSQL async migration issues | Maintain sync engine for Alembic; test migrations in CI |
| ReactFlow bundle size | Code-split DAG visualization; lazy load on plan display |
| OpenAI API costs in MOCK mode | Skip LLM call when template matches; cache common plans |
| WebSocket connection reliability | Implement automatic reconnection with exponential backoff |

---

## Appendix A: Cross-Reference Index

### Requirements → Sections Mapping

| Requirement ID | Section(s) | Key Detail |
|---|---|---|
| FR-01 | 1.3 (POST /commands), 3.1 (CommandRequest) | Command text validation, max 2000 chars |
| FR-02 | 3.1 (IntentClassification) | Multi-label intent classification |
| FR-06 | 3.1 (ExecutionPlan, PlanStep) | DAG validation, dependency resolution |
| FR-09 | 1.3 (POST /executions/{id}/approve), 3.1 (RiskLevel) | Plan confirmation flow, auto-approve flag |
| FR-11 | 4 (all MCP servers), 1.3 (GET /admin/tools) | Tool discovery, schema caching |
| FR-13 | 3.1 (ExecutionPlan), 8.4 (TaskGroup) | asyncio.TaskGroup parallel execution |
| FR-15 | 3.1 (PlanStep.condition), 4.9 (threshold_check) | Conditional step execution |
| FR-17 | 8.3 (Redis circuit breaker), 2.2 (mcp_server_states) | Circuit breaker state machine |
| FR-19 | 1.3 (SSE escalation event), 1.3 (POST escalation) | Human-in-the-loop escalation |
| FR-21 | 2.2 (Execution, StepResult), 3.1 (ExecutionState) | State persistence after every step |
| FR-22 | 8.5 (SIGTERM handler), 3.1 (ExecutionState) | Graceful shutdown, state preservation |
| FR-25 | 2.2 (audit_logs table), 3.1 (AuditLogEntry) | Structured audit logging |
| FR-26 | 9 (secret redaction in tests), 8.5 (redaction) | Secret stripping from all logs |
| FR-29 | 5 (ModeConfiguration), 1.3 (GET /admin/mode) | Three execution modes |
| FR-30 | 4.10 (seed derivation), 4.3–4.9 (all mocks) | Deterministic mock data |
| FR-32 | 1.3 (POST /admin/mode), 5.5 (runtime switching) | Runtime mode change |
| FR-33 | 1.3 (all responses), 6.4 (ModeIndicator) | Mode indication in all responses |
| FR-42 | 5 (full config schema), 3.4 (Pydantic-Settings) | Hierarchical config loading |
| NFR-01 | 10.8 (performance testing), 8.4 (planning) | < 2s E2E single-tool |
| NFR-06 | 1.3 (GET /health), 7.1 (healthcheck config) | 99.9% uptime target |
| NFR-10 | 5.2 (env var only), 9 (security scan) | Zero secret leakage |
| NFR-11 | 1.1 (auth), 9.3 (integration auth tests) | API key on all endpoints |
| NFR-13 | 4.8 (Postgres READ-ONLY), 4.9 (safe_eval) | No injection surface |
| NFR-19 | 1.3 (GET /metrics), 7.3 (Prometheus) | Full Prometheus coverage |
| NFR-21 | 6.2 (Python 3.13), 7.1 (Docker Compose) | Python 3.13+ deployment |
| NFR-23 | 4.10 (schema parity), 9.3 (contract tests) | Mock/live schema equality |

### Architecture Cross-References

| Architecture Component | Tech Spec Section | Implementation File |
|---|---|---|
| Intent Classifier | 3.1 (IntentClassification) | `services/intent.py` |
| Intent Planner | 3.1 (ExecutionPlan) | `services/intent.py` |
| Step Executor | 8.4 (TaskGroup), 3.1 (StepResult) | `services/executor.py` |
| State Manager | 2.2 (DB schema), 3.1 (ExecutionState) | `services/state.py` |
| Error Recovery | 8.3 (circuit breaker), 3.1 (StepError) | `services/recovery.py` |
| MCP Hub | 4.1 (base), 4.2 (error modes) | `infra/mcp_hub.py` |
| Tool Registry | 1.3 (GET /admin/tools) | `infra/mcp_hub.py` |
| Mock Factory | 4.10 (seed), 4.3–4.9 (per-server) | `infra/mock_factory.py` |
| Audit Logger | 2.2 (audit_logs table) | `services/audit.py` |
| Auth Middleware | 1.1 (auth tiers) | `api/middleware/auth.py` |

---

*End of Technical Specification*

