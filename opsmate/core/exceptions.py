"""Custom exceptions for mcp-opsmate."""

from __future__ import annotations

from typing import Any


class OpsMateError(Exception):
    """Base exception for all opsmate errors."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class PlanningError(OpsMateError):
    """Raised when intent classification or plan generation fails."""

    pass


class ExecutionError(OpsMateError):
    """Raised when step execution encounters an irrecoverable error."""

    def __init__(
        self,
        message: str,
        *,
        step_id: str | None = None,
        tool_name: str | None = None,
        server_name: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.step_id = step_id
        self.tool_name = tool_name
        self.server_name = server_name


class MCPToolNotFoundError(ExecutionError):
    """Raised when a requested MCP tool is not found in the registry."""

    def __init__(self, tool_name: str, available_tools: list[str] | None = None) -> None:
        super().__init__(
            f"MCP tool '{tool_name}' not found in any connected server",
            tool_name=tool_name,
            details={"available_tools": available_tools or []},
        )
        self.tool_name = tool_name
        self.available_tools = available_tools or []


class MCPSchemaValidationError(ExecutionError):
    """Raised when tool call arguments fail schema validation."""

    def __init__(
        self,
        message: str,
        *,
        tool_name: str,
        schema_errors: list[dict[str, Any]],
        details: dict[str, Any] | None = None,
    ) -> None:
        merged = dict(details or {}, schema_errors=schema_errors)
        super().__init__(message, tool_name=tool_name, details=merged)
        self.schema_errors = schema_errors


class CircuitBreakerOpenError(OpsMateError):
    """Raised when a circuit breaker is open for an MCP server."""

    def __init__(self, server_name: str, circuit_state: str = "open") -> None:
        super().__init__(
            f"Circuit breaker for '{server_name}' is {circuit_state}",
            details={"server_name": server_name, "circuit_state": circuit_state},
        )
        self.server_name = server_name
        self.circuit_state = circuit_state


class HumanEscalationError(OpsMateError):
    """Raised when human-in-the-loop escalation is required."""

    def __init__(
        self,
        message: str,
        *,
        step_id: str | None = None,
        options: list[str] | None = None,
        timeout_seconds: int = 300,
        impact: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.step_id = step_id
        self.options = options or ["retry", "skip", "abort"]
        self.timeout_seconds = timeout_seconds
        self.impact = impact


class IntentClassificationError(OpsMateError):
    """Raised when intent classification confidence is below threshold."""

    def __init__(
        self,
        confidence: float,
        reason: str,
        suggested_rephrasings: list[str] | None = None,
    ) -> None:
        super().__init__(
            f"Intent classification confidence ({confidence:.0%}) below threshold",
            details={
                "confidence": confidence,
                "reason": reason,
                "suggested_rephrasings": suggested_rephrasings or [],
            },
        )
        self.confidence = confidence
        self.reason = reason
        self.suggested_rephrasings = suggested_rephrasings or []


class ConfigurationError(OpsMateError):
    """Raised when configuration is invalid or missing."""

    pass


class StateTransitionError(OpsMateError):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        current_state: str,
        event: str,
        valid_transitions: list[str] | None = None,
    ) -> None:
        super().__init__(
            f"Invalid transition: cannot apply '{event}' from state '{current_state}'",
            details={
                "current_state": current_state,
                "event": event,
                "valid_transitions": valid_transitions or [],
            },
        )
        self.current_state = current_state
        self.event = event
        self.valid_transitions = valid_transitions or []
