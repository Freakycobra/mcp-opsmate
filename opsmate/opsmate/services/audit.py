"""Audit logging service for mcp-opsmate.

Provides structured JSON logging with secret redaction, execution chain
tracing, and configurable log levels.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

# Secret redaction patterns
_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'"api_key"\s*:\s*"[^"]*"', re.IGNORECASE), '"api_key": "***REDACTED***"'),
    (re.compile(r'"apikey"\s*:\s*"[^"]*"', re.IGNORECASE), '"apikey": "***REDACTED***"'),
    (re.compile(r'"token"\s*:\s*"[^"]*"', re.IGNORECASE), '"token": "***REDACTED***"'),
    (re.compile(r'"password"\s*:\s*"[^"]*"', re.IGNORECASE), '"password": "***REDACTED***"'),
    (re.compile(r'"secret"\s*:\s*"[^"]*"', re.IGNORECASE), '"secret": "***REDACTED***"'),
    (re.compile(r'"authorization"\s*:\s*"[^"]*"', re.IGNORECASE), '"authorization": "***REDACTED***"'),
    (re.compile(r'"x-api-key"\s*:\s*"[^"]*"', re.IGNORECASE), '"x-api-key": "***REDACTED***"'),
    (re.compile(r'Bearer\s+[A-Za-z0-9_\-\.]+', re.IGNORECASE), 'Bearer ***REDACTED***'),
    (re.compile(r'ghp_[A-Za-z0-9]{36}', re.IGNORECASE), '***GITHUB_TOKEN_REDACTED***'),
    (re.compile(r'xoxb-[A-Za-z0-9\-]+', re.IGNORECASE), '***SLACK_TOKEN_REDACTED***'),
    (re.compile(r'AKIA[0-9A-Z]{16}', re.IGNORECASE), '***AWS_KEY_REDACTED***'),
    (re.compile(r'sk-[a-zA-Z0-9]{48}', re.IGNORECASE), '***OPENAI_KEY_REDACTED***'),
]

# Fields that should always be redacted
_SENSITIVE_FIELDS: set[str] = {
    "api_key", "apikey", "token", "password", "secret",
    "authorization", "auth_token", "access_token", "refresh_token",
    "private_key", "credential", "credentials",
}


def redact_secrets(text: str) -> str:
    """Redact secrets from a string using regex patterns.

    Args:
        text: Input text that may contain secrets.

    Returns:
        Text with secrets replaced by placeholders.
    """
    if not text:
        return text
    result: str = text
    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact secrets from a dictionary.

    Args:
        data: Dictionary that may contain secrets.

    Returns:
        Dictionary with secrets replaced.
    """
    if not isinstance(data, dict):
        return data

    result: dict[str, Any] = {}
    for key, value in data.items():
        key_lower: str = key.lower()
        if key_lower in _SENSITIVE_FIELDS:
            result[key] = "***REDACTED***"
        elif isinstance(value, dict):
            result[key] = redact_dict(value)
        elif isinstance(value, list):
            result[key] = [
                redact_dict(item) if isinstance(item, dict) else item
                for item in value
            ]
        elif isinstance(value, str):
            result[key] = redact_secrets(value)
        else:
            result[key] = value
    return result


class AuditLogger:
    """Structured audit logger for mcp-opsmate.

    Provides:
    - Structured JSON logging
    - Secret redaction
    - Execution chain tracing
    - Configurable log levels
    """

    def __init__(
        self,
        logger_name: str = "opsmate.audit",
        level: str = "INFO",
    ) -> None:
        self._logger: logging.Logger = logging.getLogger(logger_name)
        self._level: int = getattr(logging, level.upper(), logging.INFO)
        self._logger.setLevel(self._level)

    def _log(
        self,
        level: int,
        action: str,
        execution_id: str | None = None,
        details: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> None:
        """Internal log method with redaction and formatting.

        Args:
            level: Log level (logging.INFO, etc.).
            action: Action type string.
            execution_id: Execution ID for tracing.
            details: Action-specific details (will be redacted).
            user_id: User identifier.
        """
        # Redact secrets from details
        safe_details: dict[str, Any] = redact_dict(details or {})

        log_entry: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "level": logging.getLevelName(level).lower(),
        }
        if execution_id:
            log_entry["execution_id"] = str(execution_id)
        if user_id:
            log_entry["user_id"] = user_id
        if safe_details:
            log_entry["details"] = safe_details

        log_message: str = json.dumps(log_entry, default=str)

        if level >= logging.ERROR:
            self._logger.error(log_message)
        elif level >= logging.WARNING:
            self._logger.warning(log_message)
        elif level >= logging.INFO:
            self._logger.info(log_message)
        else:
            self._logger.debug(log_message)

    def log_command_received(
        self,
        execution_id: str,
        command: str,
        execution_mode: str,
        user_id: str | None = None,
    ) -> None:
        """Log command receipt."""
        self._log(
            logging.INFO,
            "command_received",
            execution_id=execution_id,
            details={
                "command": command[:200],
                "execution_mode": execution_mode,
            },
            user_id=user_id,
        )

    def log_intent_classified(
        self,
        execution_id: str,
        intent_types: list[str],
        confidence: float,
        entities: list[dict[str, Any]] | None = None,
    ) -> None:
        """Log intent classification result."""
        self._log(
            logging.INFO,
            "intent_classified",
            execution_id=execution_id,
            details={
                "intent_types": intent_types,
                "confidence": round(confidence, 2),
                "entity_count": len(entities or []),
            },
        )

    def log_plan_generated(
        self,
        execution_id: str,
        plan_id: str,
        template_used: str | None,
        step_count: int,
        risk_level: str,
        confidence: float,
    ) -> None:
        """Log plan generation."""
        self._log(
            logging.INFO,
            "plan_generated",
            execution_id=execution_id,
            details={
                "plan_id": plan_id,
                "template_used": template_used,
                "step_count": step_count,
                "risk_level": risk_level,
                "confidence": round(confidence, 2),
            },
        )

    def log_plan_approved(
        self,
        execution_id: str,
        decision: str,
        user_id: str | None = None,
    ) -> None:
        """Log plan approval/rejection."""
        self._log(
            logging.INFO,
            f"plan_{decision}",
            execution_id=execution_id,
            details={"decision": decision},
            user_id=user_id,
        )

    def log_step_started(
        self,
        execution_id: str,
        step_id: str,
        tool_name: str,
        server_name: str,
    ) -> None:
        """Log step start."""
        self._log(
            logging.INFO,
            "step_started",
            execution_id=execution_id,
            details={
                "step_id": step_id,
                "tool_name": tool_name,
                "server_name": server_name,
            },
        )

    def log_step_completed(
        self,
        execution_id: str,
        step_id: str,
        tool_name: str,
        duration_ms: float | None = None,
    ) -> None:
        """Log step completion."""
        self._log(
            logging.INFO,
            "step_completed",
            execution_id=execution_id,
            details={
                "step_id": step_id,
                "tool_name": tool_name,
                "duration_ms": round(duration_ms, 2) if duration_ms else None,
            },
        )

    def log_step_failed(
        self,
        execution_id: str,
        step_id: str,
        tool_name: str,
        error_type: str,
        error_message: str,
        retryable: bool,
    ) -> None:
        """Log step failure."""
        self._log(
            logging.WARNING,
            "step_failed",
            execution_id=execution_id,
            details={
                "step_id": step_id,
                "tool_name": tool_name,
                "error_type": error_type,
                "error_message": error_message[:500],
                "retryable": retryable,
            },
        )

    def log_execution_completed(
        self,
        execution_id: str,
        total_duration_ms: float | None = None,
        step_count: int = 0,
        failed_steps: int = 0,
    ) -> None:
        """Log execution completion."""
        self._log(
            logging.INFO,
            "execution_completed",
            execution_id=execution_id,
            details={
                "total_duration_ms": round(total_duration_ms, 2) if total_duration_ms else None,
                "step_count": step_count,
                "failed_steps": failed_steps,
            },
        )

    def log_execution_failed(
        self,
        execution_id: str,
        failure_reason: str,
        failed_step_id: str | None = None,
    ) -> None:
        """Log execution failure."""
        self._log(
            logging.ERROR,
            "execution_failed",
            execution_id=execution_id,
            details={
                "failure_reason": failure_reason[:500],
                "failed_step_id": failed_step_id,
            },
        )

    def log_execution_cancelled(
        self,
        execution_id: str,
        reason: str,
    ) -> None:
        """Log execution cancellation."""
        self._log(
            logging.INFO,
            "execution_cancelled",
            execution_id=execution_id,
            details={"reason": reason},
        )

    def log_mode_switched(
        self,
        previous_mode: str,
        new_mode: str,
        reason: str,
        user_id: str | None = None,
    ) -> None:
        """Log execution mode switch."""
        self._log(
            logging.INFO,
            "mode_switched",
            details={
                "previous_mode": previous_mode,
                "new_mode": new_mode,
                "reason": reason,
            },
            user_id=user_id,
        )

    def log_escalation_triggered(
        self,
        execution_id: str,
        step_id: str,
        reason: str,
    ) -> None:
        """Log human escalation."""
        self._log(
            logging.WARNING,
            "escalation_triggered",
            execution_id=execution_id,
            details={
                "step_id": step_id,
                "reason": reason,
            },
        )

    def log_escalation_resolved(
        self,
        execution_id: str,
        step_id: str,
        decision: str,
    ) -> None:
        """Log escalation resolution."""
        self._log(
            logging.INFO,
            "escalation_resolved",
            execution_id=execution_id,
            details={
                "step_id": step_id,
                "decision": decision,
            },
        )

    def log_tool_registry_refresh(
        self,
        servers_discovered: int,
        tools_discovered: int,
    ) -> None:
        """Log tool registry refresh."""
        self._log(
            logging.INFO,
            "tool_registry_refreshed",
            details={
                "servers_discovered": servers_discovered,
                "tools_discovered": tools_discovered,
            },
        )

    def log_error(
        self,
        action: str,
        error: str,
        execution_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log a generic error."""
        merged: dict[str, Any] = dict(details or {})
        merged["error"] = error
        self._log(
            logging.ERROR,
            action,
            execution_id=execution_id,
            details=merged,
        )

    def log_degraded_execution(
        self,
        execution_id: str,
        skipped_steps: list[str],
        reason: str,
    ) -> None:
        """Log degraded execution (non-critical steps skipped)."""
        self._log(
            logging.WARNING,
            "degraded_execution",
            execution_id=execution_id,
            details={
                "skipped_steps": skipped_steps,
                "reason": reason,
            },
        )
