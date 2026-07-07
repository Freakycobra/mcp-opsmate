"""Error recovery service for mcp-opsmate.

Implements a 4-tier error handling strategy:
1. Retry with exponential backoff (max 3 attempts)
2. Circuit Breaker (Redis-backed, 5 failures -> OPEN, 30s recovery)
3. Degraded Execution (skip non-critical steps, continue)
4. Human Escalation (prompt user with 5-min timeout)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, TypeVar

from opsmate.core.config import get_config
from opsmate.core.constants import (
    CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS,
    CIRCUIT_BREAKER_THRESHOLD,
    CIRCUIT_BREAKER_TIMEOUT,
    DEFAULT_RETRY_BACKOFF_BASE,
    MAX_RETRIES,
    CircuitState,
    ErrorType,
)
from opsmate.core.exceptions import (
    CircuitBreakerOpenError,
    ExecutionError,
    HumanEscalationError,
)

logger: logging.Logger = logging.getLogger(__name__)

T = TypeVar("T")

# ---------------------------------------------------------------------------
# ErrorClassifier
# ---------------------------------------------------------------------------


class ErrorClassifier:
    """Classifies exceptions into actionable categories for tiered handling."""

    TRANSIENT_EXCEPTIONS: tuple[type, ...] = (
        asyncio.TimeoutError,
        ConnectionResetError,
        BrokenPipeError,
        ConnectionError,
    )

    TRANSIENT_STATUS_CODES: set[int] = {429, 500, 502, 503, 504}
    PERMANENT_STATUS_CODES: set[int] = {400, 401, 403, 404, 405}

    def classify(
        self,
        exception: Exception,
        server_name: str = "",
        tool_name: str = "",
    ) -> ErrorClassification:
        """Classify an exception into an ErrorType with handling guidance.

        Args:
            exception: The exception to classify.
            server_name: MCP server where the error occurred.
            tool_name: Tool that raised the error.

        Returns:
            ErrorClassification with type, retryable flag, and circuit breaker flag.
        """
        # Check exception type
        if isinstance(exception, self.TRANSIENT_EXCEPTIONS):
            return ErrorClassification(ErrorType.TRANSIENT, retryable=True, circuit=True)

        if isinstance(exception, asyncio.CancelledError):
            return ErrorClassification(ErrorType.TRANSIENT, retryable=True, circuit=False)

        # Check HTTP status codes
        status_code: int | None = getattr(exception, "status_code", None)
        if status_code is None:
            # Try response status code
            response = getattr(exception, "response", None)
            if response is not None:
                status_code = getattr(response, "status_code", None)

        if status_code is not None:
            if status_code in self.TRANSIENT_STATUS_CODES:
                return ErrorClassification(ErrorType.TRANSIENT, retryable=True, circuit=True)
            if status_code in self.PERMANENT_STATUS_CODES:
                return ErrorClassification(ErrorType.PERMANENT, retryable=False, circuit=True)
            if status_code == 408:
                return ErrorClassification(ErrorType.TRANSIENT, retryable=True, circuit=True)

        # Check specific error types
        from opsmate.core.exceptions import MCPToolNotFoundError, MCPSchemaValidationError

        if isinstance(exception, MCPToolNotFoundError):
            return ErrorClassification(ErrorType.CONFIGURATION, retryable=False, circuit=False)
        if isinstance(exception, MCPSchemaValidationError):
            return ErrorClassification(ErrorType.CONFIGURATION, retryable=False, circuit=False)
        if isinstance(exception, CircuitBreakerOpenError):
            return ErrorClassification(ErrorType.TRANSIENT, retryable=True, circuit=False)
        if isinstance(exception, HumanEscalationError):
            return ErrorClassification(ErrorType.PERMANENT, retryable=False, circuit=False, escalate=True)

        # Check for timeout indicators in message
        msg: str = str(exception).lower()
        if any(w in msg for w in ("timeout", "timed out", "deadline exceeded")):
            return ErrorClassification(ErrorType.TRANSIENT, retryable=True, circuit=True)

        # Default: treat unknown as transient (fail-safe)
        logger.debug(
            "Unclassified error from %s/%s: %s (defaulting to TRANSIENT)",
            server_name,
            tool_name,
            exception,
        )
        return ErrorClassification(ErrorType.TRANSIENT, retryable=True, circuit=True)


class ErrorClassification:
    """Structured error classification result."""

    def __init__(
        self,
        error_type: ErrorType,
        retryable: bool,
        circuit: bool,
        escalate: bool = False,
    ) -> None:
        self.error_type = error_type
        self.retryable = retryable
        self.circuit = circuit
        self.escalate = escalate

    def __repr__(self) -> str:
        return (
            f"ErrorClassification(type={self.error_type.value}, "
            f"retryable={self.retryable}, circuit={self.circuit})"
        )


# ---------------------------------------------------------------------------
# CircuitBreaker (in-memory implementation, Redis-backed in production)
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """Circuit breaker for MCP servers.

    Uses in-memory state storage. In production, this would be backed by Redis.
    """

    FAILURE_THRESHOLD: int = CIRCUIT_BREAKER_THRESHOLD
    RECOVERY_TIMEOUT: int = CIRCUIT_BREAKER_TIMEOUT
    HALF_OPEN_MAX_CALLS: int = CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS

    def __init__(self) -> None:
        self._states: dict[str, CircuitState] = {}
        self._failure_counts: dict[str, int] = {}
        self._last_failure_times: dict[str, datetime] = {}
        self._half_open_calls: dict[str, int] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def get_state(self, server_name: str) -> CircuitState:
        """Get current circuit state for a server."""
        async with self._lock:
            state: CircuitState = self._states.get(server_name, CircuitState.CLOSED)

            # Check if OPEN should transition to HALF_OPEN
            if state == CircuitState.OPEN:
                last_failure: datetime | None = self._last_failure_times.get(server_name)
                if last_failure:
                    elapsed: float = (
                        datetime.utcnow() - last_failure
                    ).total_seconds()
                    if elapsed >= self.RECOVERY_TIMEOUT:
                        self._states[server_name] = CircuitState.HALF_OPEN
                        self._half_open_calls[server_name] = 0
                        logger.info(
                            "Circuit for %s: OPEN -> HALF_OPEN",
                            server_name,
                        )
                        return CircuitState.HALF_OPEN

            return state

    async def call(
        self,
        server_name: str,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        """Execute an operation with circuit breaker protection.

        Args:
            server_name: The MCP server to protect.
            operation: Async callable to execute.

        Returns:
            Result of the operation.

        Raises:
            CircuitBreakerOpenError: If the circuit is open.
        """
        state: CircuitState = await self.get_state(server_name)

        if state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(server_name, circuit_state="open")

        if state == CircuitState.HALF_OPEN:
            half_open_count: int = self._half_open_calls.get(server_name, 0)
            if half_open_count >= self.HALF_OPEN_MAX_CALLS:
                raise CircuitBreakerOpenError(server_name, circuit_state="half_open_limit")
            self._half_open_calls[server_name] = half_open_count + 1

        try:
            result: T = await operation()
            await self._record_success(server_name)
            return result
        except Exception as e:
            await self._record_failure(server_name)
            raise

    async def _record_success(self, server_name: str) -> None:
        """Record a successful call."""
        async with self._lock:
            state: CircuitState = self._states.get(server_name, CircuitState.CLOSED)
            if state == CircuitState.HALF_OPEN:
                self._states[server_name] = CircuitState.CLOSED
                self._failure_counts[server_name] = 0
                self._half_open_calls[server_name] = 0
                logger.info("Circuit for %s: HALF_OPEN -> CLOSED", server_name)
            else:
                self._failure_counts[server_name] = 0

    async def _record_failure(self, server_name: str) -> None:
        """Record a failed call."""
        async with self._lock:
            count: int = self._failure_counts.get(server_name, 0) + 1
            self._failure_counts[server_name] = count
            self._last_failure_times[server_name] = datetime.utcnow()

            state: CircuitState = self._states.get(server_name, CircuitState.CLOSED)

            if state == CircuitState.HALF_OPEN:
                self._states[server_name] = CircuitState.OPEN
                logger.warning(
                    "Circuit for %s: HALF_OPEN -> OPEN (probe failed)",
                    server_name,
                )
            elif count >= self.FAILURE_THRESHOLD:
                self._states[server_name] = CircuitState.OPEN
                logger.warning(
                    "Circuit for %s: CLOSED -> OPEN (%d consecutive failures)",
                    server_name,
                    count,
                )

    async def reset(self, server_name: str) -> None:
        """Manually reset the circuit breaker for a server."""
        async with self._lock:
            self._states[server_name] = CircuitState.CLOSED
            self._failure_counts[server_name] = 0
            self._half_open_calls[server_name] = 0
            self._last_failure_times.pop(server_name, None)
            logger.info("Circuit for %s: manually reset to CLOSED", server_name)


# ---------------------------------------------------------------------------
# ErrorRecoveryHandler
# ---------------------------------------------------------------------------


class ErrorRecoveryHandler:
    """4-tier error recovery handler.

    Tiers:
    1. Retry: exponential backoff (1s, 2s, 4s), max 3 attempts
    2. Circuit Breaker: Redis-backed state machine
    3. Degraded Execution: skip non-critical steps
    4. Human Escalation: prompt user (5-min timeout)
    """

    def __init__(
        self,
        circuit_breaker: CircuitBreaker | None = None,
        max_retries: int = MAX_RETRIES,
        backoff_base: float = DEFAULT_RETRY_BACKOFF_BASE,
    ) -> None:
        self._classifier: ErrorClassifier = ErrorClassifier()
        self._circuit: CircuitBreaker = circuit_breaker or CircuitBreaker()
        self._max_retries: int = max_retries
        self._backoff_base: float = backoff_base

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Access the circuit breaker instance."""
        return self._circuit

    async def execute_with_recovery(
        self,
        server_name: str,
        tool_name: str,
        operation: Callable[[], Awaitable[T]],
        is_critical: bool = False,
    ) -> T:
        """Execute an operation with full error recovery.

        Applies all 4 tiers in order:
        1. Retry with exponential backoff for transient errors
        2. Circuit breaker protection
        3. For non-critical steps: skip on persistent failure
        4. For critical steps: human escalation

        Args:
            server_name: MCP server name.
            tool_name: Tool being called.
            operation: Async callable to execute.
            is_critical: Whether the step is critical.

        Returns:
            Operation result.

        Raises:
            HumanEscalationError: For critical step failures after retries.
            ExecutionError: For non-retryable failures.
        """
        last_exception: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                # Check circuit breaker
                result: T = await self._circuit.call(server_name, operation)
                return result

            except CircuitBreakerOpenError:
                # Circuit is open - escalate if critical, otherwise skip
                if is_critical:
                    raise HumanEscalationError(
                        f"Circuit breaker open for {server_name} during critical step",
                        options=["wait_and_retry", "skip", "abort"],
                        impact=f"Cannot reach {server_name} for {tool_name}",
                    )
                raise ExecutionError(
                    f"Circuit breaker open for {server_name}, skipping {tool_name}",
                    details={"server": server_name, "tool": tool_name},
                )

            except Exception as e:
                last_exception = e
                classification: ErrorClassification = self._classifier.classify(
                    e, server_name, tool_name
                )

                logger.warning(
                    "Attempt %d/%d failed for %s/%s: %s (type=%s, retryable=%s)",
                    attempt,
                    self._max_retries,
                    server_name,
                    tool_name,
                    e,
                    classification.error_type.value,
                    classification.retryable,
                )

                if not classification.retryable:
                    # Non-retryable error
                    if is_critical:
                        raise HumanEscalationError(
                            f"Non-retryable error in critical step {tool_name}: {e}",
                            options=["skip", "abort"],
                            impact=f"Permanent failure in {server_name}/{tool_name}",
                        )
                    raise ExecutionError(
                        f"Non-retryable error: {e}",
                        details={
                            "server": server_name,
                            "tool": tool_name,
                            "classification": classification.error_type.value,
                        },
                    )

                if attempt < self._max_retries:
                    backoff: float = self._backoff_base * (2 ** (attempt - 1))
                    logger.info("Retrying in %.1fs (attempt %d)", backoff, attempt + 1)
                    await asyncio.sleep(backoff)

        # All retries exhausted
        if is_critical:
            raise HumanEscalationError(
                f"Critical step {tool_name} failed after {self._max_retries} attempts: {last_exception}",
                options=["retry", "skip", "abort"],
                impact=f"All retries exhausted for {server_name}/{tool_name}",
            )

        raise ExecutionError(
            f"Failed after {self._max_retries} attempts: {last_exception}",
            details={"server": server_name, "tool": tool_name},
        )
