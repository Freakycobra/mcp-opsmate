"""Execution lifecycle state machine for mcp-opsmate.

Implements all 14 state transitions from architecture.md Section 4.2
with full validation that prevents invalid transitions.
"""

from __future__ import annotations

import logging
from typing import Callable

from opsmate.core.constants import ExecutionStatus
from opsmate.core.exceptions import StateTransitionError

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Transition table: (current_state, event) -> next_state
# ---------------------------------------------------------------------------

_TRANSITION_TABLE: dict[tuple[ExecutionStatus, str], ExecutionStatus] = {
    # From PENDING
    (ExecutionStatus.PENDING, "classify_start"): ExecutionStatus.PLANNING,
    # From PLANNING
    (ExecutionStatus.PLANNING, "plan_generated"): ExecutionStatus.AWAITING_CONFIRMATION,
    (ExecutionStatus.PLANNING, "single_step_auto"): ExecutionStatus.EXECUTING,
    (ExecutionStatus.PLANNING, "plan_error"): ExecutionStatus.FAILED,
    # From AWAITING_CONFIRMATION
    (ExecutionStatus.AWAITING_CONFIRMATION, "user_approve"): ExecutionStatus.EXECUTING,
    (ExecutionStatus.AWAITING_CONFIRMATION, "user_reject"): ExecutionStatus.CANCELLED,
    (ExecutionStatus.AWAITING_CONFIRMATION, "timeout"): ExecutionStatus.CANCELLED,
    # From EXECUTING
    (ExecutionStatus.EXECUTING, "all_steps_complete"): ExecutionStatus.COMPLETED,
    (ExecutionStatus.EXECUTING, "critical_step_fail"): ExecutionStatus.PAUSED,
    (ExecutionStatus.EXECUTING, "irrecoverable_error"): ExecutionStatus.FAILED,
    # From PAUSED
    (ExecutionStatus.PAUSED, "user_continue"): ExecutionStatus.EXECUTING,
    (ExecutionStatus.PAUSED, "user_abort"): ExecutionStatus.FAILED,
    (ExecutionStatus.PAUSED, "timeout"): ExecutionStatus.FAILED,
    # From terminal states (transitions persist current state for idempotency)
    (ExecutionStatus.COMPLETED, "sigterm_received"): ExecutionStatus.COMPLETED,
    (ExecutionStatus.FAILED, "sigterm_received"): ExecutionStatus.FAILED,
    (ExecutionStatus.CANCELLED, "sigterm_received"): ExecutionStatus.CANCELLED,
}

# Valid transitions per current state for error messages
_VALID_TRANSITIONS: dict[ExecutionStatus, list[str]] = {
    ExecutionStatus.PENDING: ["classify_start"],
    ExecutionStatus.PLANNING: [
        "plan_generated",
        "single_step_auto",
        "plan_error",
    ],
    ExecutionStatus.AWAITING_CONFIRMATION: [
        "user_approve",
        "user_reject",
        "timeout",
    ],
    ExecutionStatus.EXECUTING: [
        "all_steps_complete",
        "critical_step_fail",
        "irrecoverable_error",
    ],
    ExecutionStatus.PAUSED: [
        "user_continue",
        "user_abort",
        "timeout",
    ],
    ExecutionStatus.COMPLETED: ["sigterm_received"],
    ExecutionStatus.FAILED: ["sigterm_received"],
    ExecutionStatus.CANCELLED: ["sigterm_received"],
}

# Terminal states
_TERMINAL_STATES: set[ExecutionStatus] = {
    ExecutionStatus.COMPLETED,
    ExecutionStatus.FAILED,
    ExecutionStatus.CANCELLED,
}

# Human-readable descriptions for events
_EVENT_DESCRIPTIONS: dict[str, str] = {
    "classify_start": "Begin intent classification",
    "plan_generated": "Plan generated (multi-step)",
    "single_step_auto": "Single-step auto-approve",
    "plan_error": "Planning error (irrecoverable)",
    "user_approve": "User approved plan",
    "user_reject": "User rejected plan",
    "timeout": "Timeout occurred",
    "all_steps_complete": "All steps completed successfully",
    "critical_step_fail": "Critical step failed (human escalation)",
    "irrecoverable_error": "Irrecoverable error",
    "user_continue": "User continued from pause",
    "user_abort": "User aborted execution",
    "sigterm_received": "SIGTERM received (persist state)",
    "startup_resume": "Resume on startup",
}

# List of all events for validation
_ALL_EVENTS: set[str] = set(_EVENT_DESCRIPTIONS.keys())


class StateMachine:
    """Execution lifecycle state machine.

    Manages valid transitions between ExecutionStatus values.
    All transitions are validated against the transition table;
    invalid transitions raise StateTransitionError.
    """

    def __init__(self) -> None:
        self._transition_table: dict[
            tuple[ExecutionStatus, str], ExecutionStatus
        ] = dict(_TRANSITION_TABLE)
        self._callbacks: dict[str, list[Callable]] = {}

    def transition(
        self,
        current_state: ExecutionStatus,
        event: str,
        *,
        strict: bool = True,
    ) -> ExecutionStatus:
        """Compute the next state from current state and event.

        Args:
            current_state: The current execution status.
            event: The transition event name.
            strict: If True, raises StateTransitionError for invalid transitions.
                    If False, returns current state for unknown transitions.

        Returns:
            The next ExecutionStatus.

        Raises:
            StateTransitionError: If the transition is invalid and strict=True.
        """
        if current_state in _TERMINAL_STATES and event == "sigterm_received":
            # Idempotent: terminal states stay terminal on sigterm
            logger.debug("Terminal state %s on sigterm: staying put", current_state.value)
            return current_state

        key: tuple[ExecutionStatus, str] = (current_state, event)
        if key not in self._transition_table:
            if not strict:
                logger.warning(
                    "Unknown transition (%s, %s) - returning current state",
                    current_state.value,
                    event,
                )
                return current_state

            valid_events: list[str] = _VALID_TRANSITIONS.get(current_state, [])
            raise StateTransitionError(
                current_state=current_state.value,
                event=event,
                valid_transitions=valid_events,
            )

        next_state: ExecutionStatus = self._transition_table[key]
        logger.info(
            "State transition: %s --[%s]--> %s",
            current_state.value,
            event,
            next_state.value,
        )
        return next_state

    def is_terminal(self, state: ExecutionStatus) -> bool:
        """Check if a state is terminal."""
        return state in _TERMINAL_STATES

    def is_active(self, state: ExecutionStatus) -> bool:
        """Check if a state represents an active (non-terminal) execution."""
        return state not in _TERMINAL_STATES

    def can_transition(self, current_state: ExecutionStatus, event: str) -> bool:
        """Check if a transition is valid without raising."""
        key: tuple[ExecutionStatus, str] = (current_state, event)
        return key in self._transition_table

    def get_valid_events(self, state: ExecutionStatus) -> list[str]:
        """Get list of valid events for a given state."""
        return list(_VALID_TRANSITIONS.get(state, []))

    def get_event_description(self, event: str) -> str:
        """Get human-readable description for an event."""
        return _EVENT_DESCRIPTIONS.get(event, f"Unknown event: {event}")

    def get_all_events(self) -> list[str]:
        """Get all valid event names."""
        return sorted(_ALL_EVENTS)

    def add_callback(self, event: str, callback: Callable) -> None:
        """Register a callback to be invoked after a specific event transitions.

        Args:
            event: The event name to trigger the callback.
            callback: Callable to invoke. Signature: (old_state, new_state, event) -> None.
        """
        self._callbacks.setdefault(event, []).append(callback)

    def _invoke_callbacks(
        self,
        old_state: ExecutionStatus,
        new_state: ExecutionStatus,
        event: str,
    ) -> None:
        """Invoke registered callbacks for a transition."""
        for callback in self._callbacks.get(event, []):
            try:
                callback(old_state, new_state, event)
            except Exception:
                logger.exception("State transition callback failed for event %s", event)

    def transition_with_callback(
        self,
        current_state: ExecutionStatus,
        event: str,
        *,
        strict: bool = True,
    ) -> ExecutionStatus:
        """Transition and invoke registered callbacks."""
        next_state: ExecutionStatus = self.transition(current_state, event, strict=strict)
        self._invoke_callbacks(current_state, next_state, event)
        return next_state

    @property
    def all_transitions(self) -> dict[tuple[str, str], str]:
        """Return all transitions as a flat dict for inspection."""
        return {
            (k[0].value, k[1]): v.value
            for k, v in self._transition_table.items()
        }


# Global singleton instance
_state_machine: StateMachine | None = None


def get_state_machine() -> StateMachine:
    """Get or create the global StateMachine singleton."""
    global _state_machine
    if _state_machine is None:
        _state_machine = StateMachine()
    return _state_machine
