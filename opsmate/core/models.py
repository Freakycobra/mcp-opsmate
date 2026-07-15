"""Complete Pydantic v2 models for mcp-opsmate.

Includes all domain models, MCP tool input/output schemas, configuration,
and event models as specified in the technical specification.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from opsmate.core.constants import (
    CircuitState,
    ErrorType,
    ExecutionMode,
    ExecutionStatus,
    IntentType,
    RiskLevel,
    StepStatus,
)


# ============================================================================
# Seed derivation utility
# ============================================================================


def derive_seed(command_text: str, step_index: int = 0) -> int:
    """Derive a deterministic seed from command text and step index.

    Same command + step always produces identical mock data.
    """
    hash_input: bytes = f"{command_text}::{step_index}".encode("utf-8")
    hash_bytes: bytes = hashlib.sha256(hash_input).digest()
    return int.from_bytes(hash_bytes[:4], byteorder="big")


# ============================================================================
# Command Request / Response
# ============================================================================


class CommandRequest(BaseModel):
    """User command submission."""

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "text": "Check payment-service pods in EKS, restart if CPU > 80%",
            "auto_approve": False,
            "metadata": {},
            "execution_mode_override": None,
        }
    })

    text: str = Field(..., min_length=1, max_length=2000, description="Natural language command")
    auto_approve: bool = Field(default=False, description="Skip plan confirmation for single-step plans")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Optional client metadata")
    execution_mode_override: Literal["mock", "live", "mixed"] | None = Field(
        default=None, description="Per-command execution mode override"
    )


class CommandResponse(BaseModel):
    """Immediate command acceptance response."""

    execution_id: UUID
    status: ExecutionStatus = ExecutionStatus.PENDING
    message: str = "Command accepted, processing started"
    execution_mode: str
    stream_url: str


class ClarificationResponse(BaseModel):
    """Returned when intent confidence is too low."""

    execution_id: UUID | None = None
    confidence: float
    reason: str
    suggested_rephrasings: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


# ============================================================================
# Intent Classification
# ============================================================================


class ExtractedEntity(BaseModel):
    """Single extracted entity from command text."""

    type: str  # "service_name", "time_range", "threshold", "resource_id", "severity", "channel"
    value: Any
    raw_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    resolved: bool = False


class IntentClassification(BaseModel):
    """Classified intent from command text."""

    intent_types: list[IntentType] = Field(
        ..., min_length=1, description="Primary intent types (multi-label)"
    )
    entities: list[ExtractedEntity] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall classification confidence")
    command_summary: str = Field(..., description="1-sentence summary of understood intent")
    requires_clarification: bool = Field(default=False)
    clarification_prompt: str | None = None


# ============================================================================
# Execution Plan
# ============================================================================


class PlanStep(BaseModel):
    """Single step in an execution plan DAG."""

    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(..., description="Unique step identifier (e.g., 'step-1')")
    tool_name: str = Field(..., description="MCP tool to call")
    server: str = Field(..., description="MCP server name")
    description: str = Field(..., description="Human-readable step description")
    input_mapping: dict[str, str] = Field(
        default_factory=dict,
        description="Jinja2-like template mapping: {param: '{{step_id.output_field}}'}",
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="Expected output shape as JSON Schema",
    )
    critical: bool = Field(
        default=False,
        description="If True, execution halts on failure",
    )
    condition: str | None = Field(
        default=None,
        description="Jinja2 conditional expression",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="step_ids that must complete before this step runs",
    )
    estimated_duration_ms: int = Field(default=1000)

    @model_validator(mode="after")
    def check_critical_destructive(self) -> Self:
        """Auto-mark destructive operations as critical."""
        destructive_tools: set[str] = {"restart_pod", "restart_service", "delete", "modify", "send_message", "create_incident"}
        if self.tool_name in destructive_tools and not self.critical:
            self.critical = True
        return self


class ExecutionPlan(BaseModel):
    """Complete execution plan as a DAG."""

    model_config = ConfigDict(validate_assignment=True)

    plan_id: str = Field(default_factory=lambda: str(uuid4())[:8])
    template_used: str | None = Field(
        default=None,
        description="Template name if matched, null if zero-shot",
    )
    steps: list[PlanStep] = Field(..., min_length=1)
    dependencies: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Adjacency list: {step_id -> [dependent_step_ids]}",
    )
    estimated_duration_ms: int = Field(default=0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)
    explanation: str = Field(default="", description="Human-readable plan explanation")

    @model_validator(mode="after")
    def validate_dag(self) -> Self:
        """Validate no cycles and all dependencies exist."""
        step_ids: set[str] = {s.id for s in self.steps}
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    raise ValueError(f"Step '{step.id}' depends on unknown step '{dep}'")
        # Cycle detection via DFS
        visited: set[str] = set()
        rec_stack: set[str] = set()

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

    @model_validator(mode="after")
    def compute_risk_level(self) -> Self:
        """Auto-compute risk level from critical steps."""
        has_critical: bool = any(s.critical for s in self.steps)
        has_write: bool = any(
            s.tool_name in {"restart_pod", "restart_service", "send_message", "create_incident"}
            for s in self.steps
        )
        if has_critical and has_write:
            self.risk_level = RiskLevel.HIGH
        elif has_critical or has_write:
            self.risk_level = RiskLevel.MEDIUM
        else:
            self.risk_level = RiskLevel.LOW
        return self

    def get_step(self, step_id: str) -> PlanStep | None:
        """Retrieve a step by its ID."""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None


# ============================================================================
# Step Result
# ============================================================================


class StepError(BaseModel):
    """Detailed error information for a failed step."""

    classification: ErrorType
    message: str
    retryable: bool
    attempt_count: int = Field(default=1, ge=1, le=3)
    server_name: str | None = None
    tool_name: str | None = None
    input_params: dict[str, Any] | None = Field(
        default=None,
        description="Sanitized input parameters (secrets redacted)",
    )
    root_cause: str | None = None
    suggested_remediation: list[str] = Field(default_factory=list)
    stack_trace: str | None = Field(
        default=None,
        description="Only included in DEBUG mode",
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

    @model_validator(mode="after")
    def compute_duration(self) -> Self:
        """Auto-compute duration from timestamps."""
        if (
            self.duration_ms is None
            and self.started_at is not None
            and self.completed_at is not None
        ):
            self.duration_ms = (
                self.completed_at - self.started_at
            ).total_seconds() * 1000
        return self


# ============================================================================
# Execution Context
# ============================================================================


class ExecutionContext(BaseModel):
    """Mutable context object passed between steps (copy-on-write)."""

    variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Step outputs available as variables for downstream steps",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Execution-level metadata (user info, request context)",
    )
    secrets_redacted: bool = Field(default=True)

    def with_variable(self, key: str, value: Any) -> ExecutionContext:
        """Return new context with added variable (immutable update)."""
        new_vars: dict[str, Any] = dict(self.variables)
        new_vars[key] = value
        return self.model_copy(update={"variables": new_vars})

    def get_variable(self, key: str, default: Any = None) -> Any:
        """Get a variable from context, with dotted key support."""
        if "." not in key:
            return self.variables.get(key, default)
        parts: list[str] = key.split(".")
        current: Any = self.variables
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif hasattr(current, "__getitem__") and not isinstance(current, str):
                try:
                    current = current[part]
                except (KeyError, IndexError, TypeError):
                    return default
            else:
                return default
            if current is None:
                return default
        return current


# ============================================================================
# Execution State
# ============================================================================


class ExecutionState(BaseModel):
    """Full execution state persisted after every step."""

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

    def update_status(self, status: ExecutionStatus) -> ExecutionState:
        """Return a new state with updated status and timestamp."""
        return self.model_copy(update={"status": status, "updated_at": datetime.utcnow()})

    def add_result(self, result: StepResult) -> ExecutionState:
        """Return a new state with an added step result."""
        new_results: dict[str, StepResult] = dict(self.results)
        new_results[result.step_id] = result
        return self.model_copy(update={"results": new_results})

    def with_context(self, context: ExecutionContext) -> ExecutionState:
        """Return a new state with updated context."""
        return self.model_copy(update={"context": context})


# ============================================================================
# Audit Log
# ============================================================================


class AuditLogEntry(BaseModel):
    """Single audit log entry."""

    id: UUID | None = None
    execution_id: UUID | None = None
    action: str
    details: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# MCP Tool Schemas -- Tavily Search
# ============================================================================


class TavilySearchInput(BaseModel):
    """Input schema for tavily-search tool."""

    query: str = Field(..., min_length=1, max_length=1000)
    max_results: int = Field(default=5, ge=1, le=20)
    search_depth: Literal["basic", "advanced"] = "basic"


class TavilySearchResult(BaseModel):
    """Single search result."""

    title: str
    url: str
    content: str
    score: float = Field(ge=0.0, le=1.0)


class TavilySearchOutput(BaseModel):
    """Output schema for tavily-search tool."""

    results: list[TavilySearchResult]
    query: str
    total_results: int


class TavilyAnswerInput(BaseModel):
    """Input schema for tavily-answer tool."""

    query: str = Field(..., min_length=1, max_length=1000)
    include_sources: bool = True


class TavilyAnswerOutput(BaseModel):
    """Output schema for tavily-answer tool."""

    answer: str
    sources: list[TavilySearchResult] | None = None


# ============================================================================
# MCP Tool Schemas -- GitHub
# ============================================================================


class GitHubRepoInfoInput(BaseModel):
    """Input schema for github-repo_info tool."""

    owner: str
    repo: str


class GitHubRepoInfoOutput(BaseModel):
    """Output schema for github-repo_info tool."""

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
    """Input schema for github-workflow_status tool."""

    owner: str
    repo: str
    branch: str = Field(default="main")


class WorkflowRun(BaseModel):
    """Single workflow run."""

    id: int
    name: str
    status: Literal["queued", "in_progress", "completed"]
    conclusion: Literal["success", "failure", "cancelled", "skipped", "timed_out"] | None
    created_at: str
    html_url: str


class GitHubWorkflowStatusOutput(BaseModel):
    """Output schema for github-workflow_status tool."""

    branch: str
    runs: list[WorkflowRun]


class GitHubPRChecksInput(BaseModel):
    """Input schema for github-pr_checks tool."""

    owner: str
    repo: str
    pr_number: int = Field(..., ge=1)


class CheckRun(BaseModel):
    """Single check run."""

    name: str
    status: Literal["queued", "in_progress", "completed"]
    conclusion: Literal[
        "success", "failure", "neutral", "cancelled", "skipped", "timed_out", "action_required"
    ] | None


class GitHubPRChecksOutput(BaseModel):
    """Output schema for github-pr_checks tool."""

    pr_number: int
    check_runs: list[CheckRun]


# ============================================================================
# MCP Tool Schemas -- Slack
# ============================================================================


class SlackSendMessageInput(BaseModel):
    """Input schema for slack-send_message tool."""

    channel: str = Field(..., pattern=r"^#[a-z0-9_-]+$")
    text: str = Field(..., min_length=1, max_length=3000)
    thread_ts: str | None = None


class SlackSendMessageOutput(BaseModel):
    """Output schema for slack-send_message tool."""

    ok: bool
    channel: str
    ts: str
    delivery_status: Literal["delivered", "queued", "failed"]


# ============================================================================
# MCP Tool Schemas -- Jira
# ============================================================================


class JiraSearchTicketsInput(BaseModel):
    """Input schema for jira-search_tickets tool."""

    jql: str = Field(..., min_length=1, description="JQL query string")
    max_results: int = Field(default=50, ge=1, le=100)


class JiraTicket(BaseModel):
    """Single Jira ticket."""

    key: str
    summary: str
    status: str
    priority: str
    assignee: str | None
    created: str
    updated: str


class JiraSearchTicketsOutput(BaseModel):
    """Output schema for jira-search_tickets tool."""

    tickets: list[JiraTicket]
    total: int


class JiraCreateIncidentInput(BaseModel):
    """Input schema for jira-create_incident tool."""

    summary: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    priority: Literal["Highest", "High", "Medium", "Low", "Lowest"] = "High"
    labels: list[str] = Field(default_factory=lambda: ["incident", "auto-generated"])


class JiraCreateIncidentOutput(BaseModel):
    """Output schema for jira-create_incident tool."""

    key: str
    url: str
    status: str


# ============================================================================
# MCP Tool Schemas -- AWS ECS
# ============================================================================


class AWSDescribePodsInput(BaseModel):
    """Input schema for aws-describe_pods tool."""

    namespace: str = Field(..., pattern=r"^[a-z0-9-]+$")
    service: str = Field(..., pattern=r"^[a-z0-9-]+$")


class PodStatus(BaseModel):
    """Status of a single pod."""

    name: str
    namespace: str
    status: Literal["Running", "Pending", "CrashLoopBackOff", "Error", "Succeeded"]
    restarts: int
    cpu_percent: float = Field(ge=0.0, le=100.0)
    memory_percent: float = Field(ge=0.0, le=100.0)
    age: str
    node: str | None = None


class AWSDescribePodsOutput(BaseModel):
    """Output schema for aws-describe_pods tool."""

    pods: list[PodStatus]
    namespace: str
    service: str
    total_pods: int


class AWSGetMetricsInput(BaseModel):
    """Input schema for aws-get_metrics tool."""

    namespace: str
    service: str
    metric: Literal["cpu", "memory", "requests", "errors", "latency"]
    duration_minutes: int = Field(default=120, ge=5, le=10080)


class MetricDatapoint(BaseModel):
    """Single CloudWatch metric datapoint."""

    timestamp: str
    value: float
    unit: str


class AWSGetMetricsOutput(BaseModel):
    """Output schema for aws-get_metrics tool."""

    metric: str
    datapoints: list[MetricDatapoint]
    statistics: dict[str, float]


class AWSRestartPodInput(BaseModel):
    """Input schema for aws-restart_pod tool."""

    namespace: str
    pod_name: str
    graceful: bool = True


class AWSRestartPodOutput(BaseModel):
    """Output schema for aws-restart_pod tool."""

    pod_name: str
    namespace: str
    previous_status: str
    restart_initiated: bool
    message: str


# ============================================================================
# MCP Tool Schemas -- PostgreSQL (READ-ONLY)
# ============================================================================


class PostgresExecuteQueryInput(BaseModel):
    """Input schema for postgres-execute_query tool. READ-ONLY enforced."""

    sql: str = Field(..., min_length=1)
    params: list[Any] = Field(default_factory=list)

    @field_validator("sql")
    @classmethod
    def reject_write_operations(cls, v: str) -> str:
        """Block destructive SQL at the schema level."""
        write_keywords: set[str] = {
            "insert", "update", "delete", "drop", "alter",
            "create", "truncate", "grant", "revoke",
        }
        first_token: str = v.strip().split()[0].lower()
        if first_token in write_keywords:
            raise ValueError(f"Write operations are blocked. Found: '{first_token.upper()}'")
        return v


class PostgresExecuteQueryOutput(BaseModel):
    """Output schema for postgres-execute_query tool."""

    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    execution_time_ms: float


# ============================================================================
# MCP Tool Schemas -- Calculator
# ============================================================================


class CalculatorMathInput(BaseModel):
    """Input schema for calculator-math tool."""

    expression: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Math expression e.g., '(100 - 80) / 80 * 100'",
    )


class CalculatorMathOutput(BaseModel):
    """Output schema for calculator-math tool."""

    result: float
    expression: str
    unit: str | None = None


class CalculatorDateInput(BaseModel):
    """Input schema for calculator-date_calc tool."""

    expression: str = Field(
        ...,
        description="Date expression e.g., 'now - 7 days', 'days_between(2024-01-01, 2024-06-01)'",
    )


class CalculatorDateOutput(BaseModel):
    """Output schema for calculator-date_calc tool."""

    result: str
    expression: str
    result_type: Literal["datetime", "duration", "error"]


class CalculatorThresholdInput(BaseModel):
    """Input schema for calculator-threshold_check tool."""

    value: float
    operator: Literal[">", ">=", "<", "<=", "==", "!="]
    threshold: float


class CalculatorThresholdOutput(BaseModel):
    """Output schema for calculator-threshold_check tool."""

    triggered: bool
    value: float
    operator: str
    threshold: float
    message: str


# ============================================================================
# SSE Event Models
# ============================================================================


class SSEEvent(BaseModel):
    """Base for all SSE events."""

    event_type: str
    data: dict[str, Any]
    id: str | None = None


class StepCompletedEvent(BaseModel):
    """SSE event for step completion."""

    step_id: str
    tool_name: str
    server: str
    status: str = "completed"
    output_preview: str
    started_at: datetime
    completed_at: datetime
    duration_ms: float


class StepFailedEvent(BaseModel):
    """SSE event for step failure."""

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
    """SSE event for human escalation."""

    step_id: str
    reason: str
    options: list[str]
    timeout_seconds: int = 300
    impact: str


class ExecutionCompletedEvent(BaseModel):
    """SSE event for execution completion."""

    execution_id: UUID
    status: ExecutionStatus = ExecutionStatus.COMPLETED
    summary: str
    result_preview: dict[str, Any]
    total_duration_ms: float
    completed_at: datetime


class ExecutionFailedEvent(BaseModel):
    """SSE event for execution failure."""

    execution_id: UUID
    status: ExecutionStatus = ExecutionStatus.FAILED
    failure_reason: str
    failed_step_id: str | None
    total_duration_ms: float
    completed_at: datetime


class ExecutionCancelledEvent(BaseModel):
    """SSE event for execution cancellation."""

    execution_id: UUID
    status: ExecutionStatus = ExecutionStatus.CANCELLED
    reason: str
    cancelled_at: datetime


# ============================================================================
# Health & Admin Response Models
# ============================================================================


class HealthCheckDetail(BaseModel):
    """Individual health check component result."""

    status: Literal["ok", "warning", "critical"]
    response_time_ms: float
    detail: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    uptime_seconds: float
    timestamp: datetime
    checks: dict[str, HealthCheckDetail]


class ModeConfiguration(BaseModel):
    """Execution mode configuration."""

    global_mode: Literal["mock", "live", "mixed"]
    server_overrides: dict[str, Literal["mock", "live", "local"]] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_mixed_overrides(self) -> Self:
        """Server overrides only valid when global_mode is 'mixed'."""
        if self.global_mode != "mixed" and self.server_overrides:
            raise ValueError("server_overrides only valid when global_mode='mixed'")
        return self


class ModeConfigurationResponse(BaseModel):
    """Current execution mode configuration response."""

    global_mode: Literal["mock", "live", "mixed"]
    effective_mode: Literal["mock", "live", "mixed"]
    server_modes: dict[str, Literal["mock", "live", "local"]]
    can_switch_at_runtime: bool = True
    active_executions: int
    last_changed_at: datetime | None = None
    last_changed_by: str | None = None


class ModeSwitchRequest(BaseModel):
    """Request to change execution mode."""

    global_mode: Literal["mock", "live", "mixed"]
    server_overrides: dict[str, Literal["mock", "live", "local"]] = Field(
        default_factory=dict,
        description="Per-server mode overrides. Only applied when global_mode='mixed'.",
    )
    reason: str = Field(..., min_length=1, description="Reason for mode change (audited)")
    force: bool = Field(default=False, description="Force switch even with active executions")

    @model_validator(mode="after")
    def validate_mixed_overrides(self) -> Self:
        """Server overrides only valid when global_mode is 'mixed'."""
        if self.global_mode != "mixed" and self.server_overrides:
            raise ValueError("server_overrides only valid when global_mode='mixed'")
        return self


class ModeSwitchResponse(BaseModel):
    """Result of mode switch."""

    previous_mode: str
    new_mode: str
    applied_at: datetime
    active_executions_unchanged: int
    message: str


# ============================================================================
# Tool Registry Models
# ============================================================================


class ToolInfo(BaseModel):
    """Information about a single MCP tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    server: str
    destructive: bool = False


class ServerToolsInfo(BaseModel):
    """Tools available from a single MCP server."""

    server_name: str
    transport: str
    connected: bool
    mode: Literal["mock", "live", "local"]
    tool_count: int
    tools: list[ToolInfo]


class ToolRegistryResponse(BaseModel):
    """Snapshot of the tool registry."""

    last_refreshed_at: datetime
    server_count: int
    total_tools: int
    servers: list[ServerToolsInfo]


class ToolRefreshResponse(BaseModel):
    """Result of tool registry refresh."""

    refreshed_at: datetime
    servers_discovered: int
    tools_discovered: int
    servers: list[ServerRefreshResult]


class ServerRefreshResult(BaseModel):
    """Result of refreshing a single server's tools."""

    server_name: str
    status: Literal["ok", "failed", "timeout"]
    tools_found: int
    error: str | None = None


# ============================================================================
# Plan Approval Models
# ============================================================================


class PlanApprovalRequest(BaseModel):
    """User decision on a pending execution plan."""

    decision: Literal["approve", "reject", "modify"]
    modified_plan: ExecutionPlan | None = Field(
        default=None,
        description="If decision='modify', the modified plan. Must preserve DAG validity.",
    )
    reason: str | None = Field(default=None, description="Reason for rejection/modification")

    @model_validator(mode="after")
    def validate_modify_has_plan(self) -> Self:
        """Modification requires a modified plan."""
        if self.decision == "modify" and self.modified_plan is None:
            raise ValueError("modified_plan is required when decision='modify'")
        return self


class PlanApprovalResponse(BaseModel):
    """Result of plan approval action."""

    execution_id: UUID
    decision: str
    new_status: ExecutionStatus
    message: str


# ============================================================================
# Execution List / Detail Models
# ============================================================================


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


class ExecutionListResponse(BaseModel):
    """Paginated list of executions."""

    items: list[ExecutionSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


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


# ============================================================================
# Escalation Resolution
# ============================================================================


class EscalationResolutionRequest(BaseModel):
    """User response to an escalation prompt."""

    decision: Literal["continue", "abort", "retry", "skip_step"]
    modified_step_params: dict[str, Any] | None = None
    reason: str | None = None


# ============================================================================
# Demo / Examples
# ============================================================================


class DemoCommand(BaseModel):
    """Built-in demo command for onboarding."""

    title: str
    description: str
    command: str
    expected_plan_template: str
    category: str


class ExamplesResponse(BaseModel):
    """Built-in demo commands response."""

    examples: list[DemoCommand]


# ============================================================================
# Error Response Models
# ============================================================================


class ErrorResponse(BaseModel):
    """Standard error response body."""

    error: str
    detail: str | None = None
    execution_id: UUID | None = None
    request_id: str = Field(default_factory=lambda: str(uuid4())[:8])
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
    request_id: str = Field(default_factory=lambda: str(uuid4())[:8])
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# WebSocket Models
# ============================================================================


class StepUpdatePayload(BaseModel):
    """Incremental step status change."""

    execution_id: UUID
    step_id: str
    status: StepStatus
    output: dict[str, Any] | None = None
    error: StepError | None = None
    progress_percent: float | None = None


class DAGNode(BaseModel):
    """DAG node for ReactFlow visualization."""

    id: str
    type: str
    position: dict[str, float]
    data: dict[str, Any]


class DAGEdge(BaseModel):
    """DAG edge for ReactFlow visualization."""

    id: str
    source: str
    target: str
    animated: bool = False


class DAGUpdatePayload(BaseModel):
    """DAG structure change payload."""

    execution_id: UUID
    nodes: list[DAGNode]
    edges: list[DAGEdge]


class WebSocketErrorPayload(BaseModel):
    """Server-side error payload for WebSocket."""

    code: str
    message: str
    execution_id: UUID | None = None


# ============================================================================
# Pydantic-Settings Configuration Models
# ============================================================================


class MCPSettings(BaseModel):
    """Configuration for a single MCP server."""

    transport: Literal["stdio", "sse"] = "stdio"
    command: list[str] | None = None
    url: str | None = None
    mode: Literal["mock", "live", "local"] = "mock"
    timeout: int = Field(default=30, ge=1, le=300)
    env: dict[str, str] = Field(default_factory=dict)
    critical: bool = False

    @model_validator(mode="after")
    def validate_transport_config(self) -> Self:
        """Validate that transport has required config."""
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio transport requires 'command' list")
        if self.transport == "sse" and not self.url:
            raise ValueError("sse transport requires 'url' string")
        return self


class LLMSettings(BaseModel):
    """LLM provider configuration."""

    provider: Literal["openai"] = "openai"
    model: str = "gpt-4o"
    api_key: str = Field(default="", description="Set via OPENAI_API_KEY env var")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=128000)
    planning_timeout_ms: int = Field(default=5000, ge=1000, le=30000)


class DatabaseSettings(BaseModel):
    """Database connection configuration."""

    url: str = "postgresql+asyncpg://opsmate:opsmate@localhost:5432/opsmate"
    pool_size: int = Field(default=10, ge=1, le=100)
    max_overflow: int = Field(default=20, ge=0, le=100)
    echo: bool = False


class CacheSettings(BaseModel):
    """Redis cache configuration."""

    url: str = "redis://localhost:6379/0"
    ttl: int = Field(default=3600, ge=60)
    circuit_breaker_ttl: int = Field(default=30, description="Circuit breaker state TTL in seconds")


class LoggingSettings(BaseModel):
    """Logging configuration."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: Literal["json", "text"] = "json"
    output: Literal["stdout", "stderr", "file"] = "stdout"
    file_path: str | None = None


class AppSettings(BaseModel):
    """Application-level configuration."""

    name: str = "mcp-opsmate"
    version: str = "1.0.0"
    execution_mode: Literal["mock", "live", "mixed"] = "mock"
    auto_approve: bool = False
    max_concurrent_steps: int = Field(default=10, ge=1, le=50)
    plan_confirmation_required: bool = True
    retention_days: int = Field(default=30, ge=1)
