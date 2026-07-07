"""Rich-based output rendering for the OpsMate CLI.

This is the primary visual layer — responsible for rendering:
- Execution plans (tables, risk badges, mode indicators)
- Step results (syntax-highlighted JSON, timing)
- Progress spinners during execution
- Final summaries with execution statistics
- Error displays with helpful suggestions
- Execution history tables

Design principles:
- Every render method returns a Rich Renderable (not prints directly)
- Consistent color scheme: green=success, red=error, yellow=warning, blue=info
- MOCK mode is always visually distinct (amber/orange accent)
- LIVE mode uses green accent
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, ConsoleRenderable, Group
from rich.json import JSON
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.status import Status
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from opsmate_cli.models import (
    ErrorType,
    ExecutionDetailResponse,
    ExecutionListResponse,
    ExecutionMode,
    ExecutionPlan,
    ExecutionStatus,
    HealthResponse,
    PlanStep,
    RiskLevel,
    StepResult,
    StepStatus,
)


# ── Color Constants ───────────────────────────────────────────────────────────

RISK_COLORS = {
    RiskLevel.LOW: "green",
    RiskLevel.MEDIUM: "yellow",
    RiskLevel.HIGH: "red",
}

RISK_EMOJI = {
    RiskLevel.LOW: "✓",
    RiskLevel.MEDIUM: "⚠",
    RiskLevel.HIGH: "✖",
}

MODE_COLORS = {
    ExecutionMode.MOCK: "bold amber3",
    ExecutionMode.LIVE: "bold green4",
    ExecutionMode.MIXED: "bold blue3",
}

STATUS_COLORS = {
    ExecutionStatus.PENDING: "dim",
    ExecutionStatus.PLANNING: "cyan",
    ExecutionStatus.AWAITING_CONFIRMATION: "yellow",
    ExecutionStatus.EXECUTING: "bold blue",
    ExecutionStatus.PAUSED: "magenta",
    ExecutionStatus.COMPLETED: "bold green",
    ExecutionStatus.FAILED: "bold red",
    ExecutionStatus.CANCELLED: "dim red",
}

STEP_STATUS_COLORS = {
    StepStatus.PENDING: "dim",
    StepStatus.RUNNING: "bold blue",
    StepStatus.COMPLETED: "bold green",
    StepStatus.FAILED: "bold red",
    StepStatus.SKIPPED: "dim yellow",
    StepStatus.SKIPPED_DUE_TO_DEPENDENCY: "dim",
    StepStatus.RETRYING: "bold yellow",
}

ERROR_TYPE_COLORS = {
    ErrorType.TRANSIENT: "yellow",
    ErrorType.PERMANENT: "red",
    ErrorType.CONFIGURATION: "magenta",
    ErrorType.UNKNOWN: "dim",
}

HEALTH_STATUS_COLORS = {
    "healthy": "bold green",
    "degraded": "bold yellow",
    "unhealthy": "bold red",
}

HEALTH_CHECK_COLORS = {
    "ok": "green",
    "warning": "yellow",
    "critical": "red",
}


# ── Badge Helpers ─────────────────────────────────────────────────────────────


def _badge(label: str, color: str, *, padding: int = 1) -> Text:
    """Create a colored badge text."""
    return Text(f"{' ' * padding}{label}{' ' * padding}", style=f"{color} on default")


def _dot(status: str, color_map: dict[str, str]) -> Text:
    """Create a colored dot indicator."""
    color = color_map.get(status, "white")
    return Text("● ", style=color)


def format_duration_ms(duration_ms: float | None) -> str:
    """Format duration in milliseconds to human-readable string.

    Args:
        duration_ms: Duration in milliseconds.

    Returns:
        Human-readable duration string (e.g., "1.2s", "350ms").
    """
    if duration_ms is None:
        return "—"
    if duration_ms >= 60000:
        minutes = int(duration_ms / 60000)
        seconds = (duration_ms % 60000) / 1000
        return f"{minutes}m{seconds:.1f}s"
    if duration_ms >= 1000:
        return f"{duration_ms / 1000:.2f}s"
    return f"{duration_ms:.0f}ms"


def format_timestamp(dt: datetime | None) -> str:
    """Format datetime for display.

    Args:
        dt: Datetime object or None.

    Returns:
        Formatted timestamp string.
    """
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ── Mode Badge ────────────────────────────────────────────────────────────────


class ModeBadge:
    """Persistent MOCK/LIVE/MIXED mode indicator."""

    def __init__(self, mode: ExecutionMode | str) -> None:
        self.mode = ExecutionMode(mode) if isinstance(mode, str) else mode

    def __rich__(self) -> Text:
        color = MODE_COLORS.get(self.mode, "white")
        mode_label = self.mode.value.upper()
        return Text(f" {mode_label} ", style=f"bold black on {color.split()[-1] if ' ' in color else color}")

    @classmethod
    def from_string(cls, mode: str) -> "ModeBadge":
        return cls(ExecutionMode(mode))


# ── Plan Renderer ─────────────────────────────────────────────────────────────


class PlanRenderer:
    """Render execution plans as beautiful Rich panels."""

    def __init__(self, plan: ExecutionPlan, execution_mode: str = "mock") -> None:
        self.plan = plan
        self.execution_mode = execution_mode

    def render(self) -> Panel:
        """Render the full plan as a Rich Panel.

        Returns:
            Rich Panel containing plan table, risk badge, and mode badge.
        """
        # Header with risk and mode badges
        risk_color = RISK_COLORS.get(self.plan.risk_level, "white")
        risk_badge = _badge(self.plan.risk_level.value, f"bold {risk_color}")
        mode_badge = ModeBadge(self.execution_mode).__rich__()

        header = Text.assemble(
            "Execution Plan ",
            risk_badge,
            "  ",
            mode_badge,
        )

        if self.plan.explanation:
            header.append(f"\n\n{self.plan.explanation}", style="dim")

        # Steps table
        table = self._build_steps_table()

        # Dependencies tree
        deps = self._build_dependencies()

        content: ConsoleRenderable
        if deps:
            content = Group(table, Text(), deps)
        else:
            content = table

        return Panel(
            content,
            title=header,
            border_style=risk_color,
            box=box.ROUNDED,
            padding=(1, 2),
        )

    def _build_steps_table(self) -> Table:
        """Build the steps table.

        Returns:
            Rich Table with step details.
        """
        table = Table(
            show_header=True,
            header_style="bold",
            box=box.SIMPLE_HEAVY,
            expand=True,
            pad_edge=False,
        )
        table.add_column("#", style="bold dim", width=3, justify="right")
        table.add_column("Step", style="bold", min_width=20)
        table.add_column("Tool", min_width=15)
        table.add_column("Server", min_width=12)
        table.add_column("Status", width=12)
        table.add_column("Deps", min_width=8)
        table.add_column("Risk", width=8)

        for i, step in enumerate(self.plan.steps, 1):
            status_dot = Text("●", style="yellow" if step.critical else "green")
            status_text = Text(" CRITICAL" if step.critical else " normal", style="red bold" if step.critical else "green")
            status = Text.assemble(status_dot, status_text)

            deps_str = ", ".join(step.dependencies) if step.dependencies else "—"

            risk = Text("HIGH", style="bold red") if step.critical else Text("low", style="dim green")

            table.add_row(
                str(i),
                step.description or step.id,
                step.tool_name,
                step.server,
                status,
                deps_str,
                risk,
            )

        return table

    def _build_dependencies(self) -> Tree | Text:
        """Build dependency tree.

        Returns:
            Rich Tree showing step dependencies, or empty Text if none.
        """
        if not self.plan.dependencies:
            return Text("")

        tree = Tree("[bold]Dependencies[/bold]")
        for step_id, deps in self.plan.dependencies.items():
            if deps:
                branch = tree.add(f"[bold]{step_id}[/bold]")
                for dep in deps:
                    branch.add(f"← {dep}")
            else:
                tree.add(f"[bold]{step_id}[/bold] [dim](no dependencies)[/dim]")

        return tree


# ── Step Result Renderer ──────────────────────────────────────────────────────


class StepResultRenderer:
    """Render completed step results."""

    def __init__(self, result: StepResult) -> None:
        self.result = result

    def render(self) -> Panel:
        """Render step result as a panel.

        Returns:
            Rich Panel with syntax-highlighted output and timing.
        """
        status_color = STEP_STATUS_COLORS.get(self.result.status, "white")
        status_text = Text(f" {self.result.status.value.upper()} ", style=f"bold {status_color}")

        # Build content
        parts: list[ConsoleRenderable] = []

        # Timing info
        timing = Text.assemble(
            "Duration: ",
            (format_duration_ms(self.result.duration_ms), "bold"),
        )
        if self.result.attempt_count > 1:
            timing.append(f"  |  Attempts: {self.result.attempt_count}", style="yellow")
        parts.append(timing)

        # Output or error
        if self.result.error:
            error_color = ERROR_TYPE_COLORS.get(self.result.error.classification, "red")
            parts.append(Text())
            parts.append(Text(f"Error ({self.result.error.classification.value}):", style=f"bold {error_color}"))
            parts.append(Panel(
                self.result.error.message,
                border_style=error_color,
                box=box.SIMPLE,
            ))
            if self.result.error.retryable:
                parts.append(Text("↻ This error is retryable", style="dim yellow"))

        elif self.result.output:
            parts.append(Text())
            output_json = json.dumps(self.result.output, indent=2, default=str)
            parts.append(JSON(output_json))

        else:
            parts.append(Text())
            parts.append(Text("(no output)", style="dim"))

        content: ConsoleRenderable = Group(*parts) if len(parts) > 1 else parts[0]

        title = Text.assemble(
            f"Step: {self.result.step_id} ",
            f"({self.result.tool_name}@{self.result.server}) ",
            status_text,
        )

        return Panel(
            content,
            title=title,
            border_style=status_color,
            box=box.ROUNDED,
            padding=(1, 2),
        )


# ── Spinner Renderer ──────────────────────────────────────────────────────────


class SpinnerRenderer:
    """Show animated spinner with status text during execution."""

    def __init__(
        self,
        message: str = "Processing...",
        console: Console | None = None,
    ) -> None:
        self.message = message
        self.console = console or Console()
        self._status: Status | None = None
        self._live: Live | None = None

    def start(self) -> None:
        """Start the spinner."""
        spinner = Spinner("dots", text=Text(self.message, style="bold blue"))
        self._live = Live(
            spinner,
            console=self.console,
            refresh_per_second=12,
            transient=True,
        )
        self._live.start()

    def update(self, message: str) -> None:
        """Update spinner message.

        Args:
            message: New status message.
        """
        self.message = message
        if self._live:
            spinner = Spinner("dots", text=Text(message, style="bold blue"))
            self._live.update(spinner)

    def stop(self) -> None:
        """Stop the spinner."""
        if self._live:
            self._live.stop()
            self._live = None

    def __enter__(self) -> "SpinnerRenderer":
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()


# ── Final Output Renderer ─────────────────────────────────────────────────────


class FinalOutputRenderer:
    """Render final execution output with summary."""

    def __init__(self, execution: ExecutionDetailResponse) -> None:
        self.execution = execution

    def render(self) -> Panel:
        """Render final output as a comprehensive panel.

        Returns:
            Rich Panel with summary table, timing, mode indicator, and warnings.
        """
        status_color = STATUS_COLORS.get(self.execution.status, "white")
        mode_badge = ModeBadge(self.execution.execution_mode).__rich__()

        parts: list[ConsoleRenderable] = []

        # Summary table of all steps
        if self.execution.results:
            parts.append(self._build_summary_table())
            parts.append(Text())

        # Timing info
        timing_table = Table(show_header=False, box=None, pad_edge=False)
        timing_table.add_column("Label", style="dim", width=20)
        timing_table.add_column("Value", style="bold")

        timing_table.add_row("Total Duration", format_duration_ms(self.execution.total_duration_ms))
        timing_table.add_row("Planning Duration", format_duration_ms(self.execution.planning_duration_ms))
        timing_table.add_row("Started", format_timestamp(self.execution.created_at))
        if self.execution.completed_at:
            timing_table.add_row("Completed", format_timestamp(self.execution.completed_at))

        parts.append(timing_table)

        # Mode indicator
        parts.append(Text())
        parts.append(Text.assemble("Execution Mode: ", mode_badge))

        # Warnings about degraded results
        warnings = self._build_warnings()
        if warnings:
            parts.append(Text())
            parts.append(warnings)

        content: ConsoleRenderable = Group(*parts)

        title = Text.assemble(
            f"Execution {str(self.execution.execution_id)[:8]}... ",
            Text(f" {self.execution.status.value.upper()} ", style=f"bold {status_color}"),
            "  ",
            mode_badge,
        )

        return Panel(
            content,
            title=title,
            border_style=status_color,
            box=box.HEAVY if self.execution.status == ExecutionStatus.COMPLETED else box.ROUNDED,
            padding=(1, 2),
        )

    def _build_summary_table(self) -> Table:
        """Build summary table of all step results.

        Returns:
            Rich Table with step results.
        """
        table = Table(
            title="[bold]Step Results[/bold]",
            show_header=True,
            header_style="bold",
            box=box.SIMPLE_HEAVY,
            expand=True,
        )
        table.add_column("Step", style="bold")
        table.add_column("Tool")
        table.add_column("Server")
        table.add_column("Status", width=12)
        table.add_column("Duration", justify="right", width=12)
        table.add_column("Output", width=8)

        for step_id, result in sorted(self.execution.results.items()):
            status_color = STEP_STATUS_COLORS.get(result.status, "white")
            status_text = Text(result.status.value.upper(), style=status_color)

            has_output = "✓" if result.output else "—"
            output_color = "green" if result.output else "dim"

            table.add_row(
                result.step_id,
                result.tool_name,
                result.server,
                status_text,
                format_duration_ms(result.duration_ms),
                Text(has_output, style=output_color),
            )

        return table

    def _build_warnings(self) -> Panel | Text:
        """Build warnings panel for degraded results.

        Returns:
            Rich Panel with warnings, or empty Text if none.
        """
        warnings: list[str] = []

        failed_steps = [r for r in self.execution.results.values() if r.status == StepStatus.FAILED]
        skipped_steps = [r for r in self.execution.results.values() if r.status in (
            StepStatus.SKIPPED, StepStatus.SKIPPED_DUE_TO_DEPENDENCY
        )]

        if failed_steps:
            step_names = ", ".join(s.step_id for s in failed_steps)
            warnings.append(f"⚠ {len(failed_steps)} step(s) failed: {step_names}")

        if skipped_steps:
            step_names = ", ".join(s.step_id for s in skipped_steps)
            warnings.append(f"⚠ {len(skipped_steps)} step(s) skipped: {step_names}")

        if not warnings:
            return Text("")

        warning_text = Text("\n").join(Text(w, style="yellow") for w in warnings)
        return Panel(
            warning_text,
            title="[bold yellow]Warnings[/bold yellow]",
            border_style="yellow",
            box=box.ROUNDED,
        )


# ── Execution List Renderer ───────────────────────────────────────────────────


class ExecutionListRenderer:
    """Render execution history as a table."""

    def __init__(self, response: ExecutionListResponse) -> None:
        self.response = response

    def render(self) -> Table:
        """Render execution list as a Rich Table.

        Returns:
            Rich Table with execution history.
        """
        table = Table(
            title=f"[bold]Execution History[/bold]  [dim]({self.response.total} total)[/dim]",
            show_header=True,
            header_style="bold",
            box=box.SIMPLE_HEAVY,
            expand=True,
            row_styles=["", "dim"],
        )
        table.add_column("ID", style="bold cyan", width=10)
        table.add_column("Command", min_width=30, max_width=60)
        table.add_column("Status", width=14)
        table.add_column("Mode", width=8)
        table.add_column("Steps", width=6, justify="right")
        table.add_column("Failed", width=6, justify="right")
        table.add_column("Duration", width=12, justify="right")
        table.add_column("Started", width=20)

        for summary in self.response.items:
            status_color = STATUS_COLORS.get(summary.status, "white")
            status_text = Text(summary.status.value.upper(), style=status_color)

            mode_color = MODE_COLORS.get(ExecutionMode(summary.execution_mode), "white")
            mode_text = Text(summary.execution_mode.upper(), style=mode_color)

            # Truncate command text
            cmd = summary.command_text
            if len(cmd) > 57:
                cmd = cmd[:54] + "..."

            table.add_row(
                str(summary.execution_id)[:8],
                cmd,
                status_text,
                mode_text,
                str(summary.step_count),
                Text(str(summary.failed_steps), style="red" if summary.failed_steps > 0 else "dim"),
                format_duration_ms(summary.total_duration_ms),
                format_timestamp(summary.created_at),
            )

        return table


# ── Error Renderer ────────────────────────────────────────────────────────────


class ErrorRenderer:
    """Formatted error display with suggestions."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def render(self) -> Panel:
        """Render error as a formatted panel with suggestions.

        Returns:
            Rich Panel with error details and helpful suggestions.
        """
        parts: list[ConsoleRenderable] = []

        # Error type and message
        error_type = type(self.error).__name__
        error_message = str(self.error)

        parts.append(Text.assemble(
            ("Error: ", "bold red"),
            (error_type, "bold red"),
        ))
        parts.append(Text())
        parts.append(Panel(
            error_message or "An unknown error occurred.",
            border_style="red",
            box=box.SIMPLE,
        ))

        # Suggestions
        suggestions = self._get_suggestions()
        if suggestions:
            parts.append(Text())
            parts.append(Text("Suggestions:", style="bold yellow"))
            for suggestion in suggestions:
                parts.append(Text(f"  • {suggestion}", style="yellow"))

        content: ConsoleRenderable = Group(*parts)

        return Panel(
            content,
            title="[bold red]✖ Error[/bold red]",
            border_style="red",
            box=box.HEAVY,
            padding=(1, 2),
        )

    def _get_suggestions(self) -> list[str]:
        """Get context-aware suggestions based on error type.

        Returns:
            List of suggestion strings.
        """
        from opsmate_cli.client import (
            APIError,
            AuthenticationError,
            ClarificationRequiredError,
            ServerUnavailableError,
            ValidationError,
        )

        suggestions: list[str] = []

        if isinstance(self.error, AuthenticationError):
            suggestions.extend([
                "Check that your API key is set: opsmate config set api_key YOUR_KEY",
                "Verify the API key in the backend configuration",
                "Set via environment: export OPS_MATE_API_KEY=your_key",
            ])
        elif isinstance(self.error, ServerUnavailableError):
            suggestions.extend([
                "Check that the backend is running: opsmate status",
                f"Verify the API URL: opsmate config show",
                "Start the backend server (docker compose up)",
            ])
        elif isinstance(self.error, ValidationError):
            suggestions.extend([
                "Check your command syntax and length (max 2000 chars)",
                "Review the command format requirements",
            ])
        elif isinstance(self.error, ClarificationRequiredError):
            suggestions.extend([
                "Try rephrasing your command with more specific terms",
                "Use one of the suggested rephrasings shown above",
                "Run 'opsmate examples' to see example commands",
            ])
        elif isinstance(self.error, APIError):
            status = getattr(self.error, "status_code", None)
            if status == 404:
                suggestions.append("Verify the execution ID is correct.")
            elif status == 409:
                suggestions.append("The execution is not in a state that supports this action.")
            elif status == 503:
                suggestions.extend([
                    "Required MCP servers may be unavailable",
                    "Try running in MOCK mode: --mode mock",
                ])
        else:
            suggestions.extend([
                "Check your network connection",
                "Verify the backend is running with 'opsmate status'",
                "Run with --verbose for more details",
            ])

        return suggestions


# ── Health Renderer ───────────────────────────────────────────────────────────


class HealthRenderer:
    """Render health check results."""

    def __init__(self, health: HealthResponse) -> None:
        self.health = health

    def render(self) -> Panel:
        """Render health status as a panel.

        Returns:
            Rich Panel with health status and check details.
        """
        status_color = HEALTH_STATUS_COLORS.get(self.health.status, "white")

        parts: list[ConsoleRenderable] = []

        # Overall status
        parts.append(Text.assemble(
            "Status: ",
            Text(f" {self.health.status.upper()} ", style=f"bold black on {status_color.split()[-1] if ' ' in status_color else status_color}"),
        ))

        parts.append(Text.assemble(
            "\nVersion: ", (self.health.version, "bold"),
            "  |  Uptime: ", (f"{self.health.uptime_seconds:.0f}s", "bold"),
        ))

        # Individual checks
        if self.health.checks:
            parts.append(Text())
            table = Table(show_header=True, header_style="bold", box=box.SIMPLE, expand=True)
            table.add_column("Service")
            table.add_column("Status", width=12)
            table.add_column("Response Time", width=14, justify="right")
            table.add_column("Detail")

            for service, check in sorted(self.health.checks.items()):
                check_color = HEALTH_CHECK_COLORS.get(check.status, "white")
                status_text = Text(check.status.upper(), style=check_color)
                table.add_row(
                    service,
                    status_text,
                    f"{check.response_time_ms:.1f}ms",
                    check.detail or "—",
                )

            parts.append(table)

        content: ConsoleRenderable = Group(*parts)

        return Panel(
            content,
            title=f"[bold]Backend Health[/bold]  [dim]{format_timestamp(self.health.timestamp)}[/dim]",
            border_style=status_color,
            box=box.ROUNDED,
            padding=(1, 2),
        )


# ── Examples Renderer ─────────────────────────────────────────────────────────


class ExamplesRenderer:
    """Render demo commands."""

    def __init__(self, examples: list[Any]) -> None:
        self.examples = examples

    def render(self) -> Table:
        """Render examples as a table.

        Returns:
            Rich Table with demo commands.
        """
        table = Table(
            title="[bold]Example Commands[/bold]  [dim]Run with: opsmate run \"<command>\"[/dim]",
            show_header=True,
            header_style="bold",
            box=box.SIMPLE_HEAVY,
            expand=True,
            row_styles=["", "dim"],
        )
        table.add_column("#", style="bold dim", width=4, justify="right")
        table.add_column("Category", width=12)
        table.add_column("Title", style="bold", min_width=20)
        table.add_column("Description", min_width=30)
        table.add_column("Command", style="cyan", min_width=30)

        for i, example in enumerate(self.examples, 1):
            category_color = {
                "health": "green",
                "incident": "red",
                "analysis": "blue",
                "correlation": "magenta",
            }.get(example.category, "white")

            table.add_row(
                str(i),
                Text(example.category.upper(), style=category_color),
                example.title,
                example.description,
                f'opsmate run "{example.command}"',
            )

        return table


# ── Plan Confirmation Prompt ──────────────────────────────────────────────────


def render_plan_confirmation(plan: ExecutionPlan, execution_mode: str) -> Panel:
    """Render plan confirmation prompt.

    Args:
        plan: Execution plan to display.
        execution_mode: Current execution mode.

    Returns:
        Rich Panel with plan and prompt.
    """
    renderer = PlanRenderer(plan, execution_mode)
    plan_panel = renderer.render()

    prompt = Text.assemble(
        "\n",
        ("Approve this plan? ", "bold"),
        ("[y]", "bold green"),
        "es / ",
        ("[n]", "bold red"),
        "o / ",
        ("[m]", "bold yellow"),
        "odify: ",
    )

    return Panel(
        Group(plan_panel, prompt),
        border_style="yellow",
        box=box.HEAVY,
        title="[bold yellow]Plan Confirmation Required[/bold yellow]",
    )


# ── Escalation Prompt ─────────────────────────────────────────────────────────


def render_escalation(event_data: dict[str, Any]) -> Panel:
    """Render human-in-the-loop escalation prompt.

    Args:
        event_data: Escalation event data.

    Returns:
        Rich Panel with escalation details and options.
    """
    parts: list[ConsoleRenderable] = []

    parts.append(Text.assemble(
        ("Step: ", "bold"),
        (event_data.get("step_id", "unknown"), "bold red"),
    ))
    parts.append(Text())
    parts.append(Text(event_data.get("reason", "Human intervention required")))

    impact = event_data.get("impact", "")
    if impact:
        parts.append(Text())
        parts.append(Text.assemble(("Impact: ", "bold yellow"), impact))

    timeout = event_data.get("timeout_seconds", 300)
    parts.append(Text.assemble(
        "\nTimeout: ",
        (f"{timeout}s", "bold"),
        " (auto-abort if no response)",
        style="dim",
    ))

    options = event_data.get("options", ["retry", "skip", "abort"])
    parts.append(Text())
    parts.append(Text("Options:", style="bold"))
    for opt in options:
        parts.append(Text(f"  [{opt[0].lower()}]{opt[1:]}" if len(opt) > 1 else f"  [{opt}]", style="cyan"))

    content: ConsoleRenderable = Group(*parts)

    return Panel(
        content,
        title="[bold magenta]⚠ Human Intervention Required[/bold magenta]",
        border_style="magenta",
        box=box.HEAVY,
        padding=(1, 2),
    )


# ── Utility Functions ─────────────────────────────────────────────────────────


def render_command_submitted(response: Any) -> Panel:
    """Render command submission acknowledgement.

    Args:
        response: CommandResponse.

    Returns:
        Rich Panel with submission details.
    """
    mode_badge = ModeBadge(response.execution_mode).__rich__()

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("Key", style="dim", width=16)
    table.add_column("Value", style="bold")

    table.add_row("Execution ID", str(response.execution_id))
    table.add_row("Status", response.status.value)
    table.add_row("Mode", mode_badge)
    table.add_row("Stream", response.stream_url)

    return Panel(
        table,
        title="[bold green]✓ Command Submitted[/bold green]",
        border_style="green",
        box=box.ROUNDED,
        padding=(1, 2),
    )


def render_step_started(event_data: dict[str, Any]) -> Text:
    """Render step started event.

    Args:
        event_data: Step started event data.

    Returns:
        Rich Text with step info.
    """
    return Text.assemble(
        ("▶ ", "bold blue"),
        (f"{event_data.get('step_id', '?')}", "bold"),
        f" — {event_data.get('tool_name', '?')}",
        f" @{event_data.get('server', '?')}",
        style="blue",
    )


def render_step_completed(event_data: dict[str, Any]) -> Text:
    """Render step completed event.

    Args:
        event_data: Step completed event data.

    Returns:
        Rich Text with completion info.
    """
    duration = event_data.get("duration_ms", 0)
    duration_str = format_duration_ms(duration)

    return Text.assemble(
        ("✓ ", "bold green"),
        (f"{event_data.get('step_id', '?')}", "bold"),
        f" — {event_data.get('tool_name', '?')}",
        f"  ({duration_str})",
        style="green",
    )


def render_step_failed(event_data: dict[str, Any]) -> Text:
    """Render step failed event.

    Args:
        event_data: Step failed event data.

    Returns:
        Rich Text with failure info.
    """
    return Text.assemble(
        ("✖ ", "bold red"),
        (f"{event_data.get('step_id', '?')}", "bold"),
        f" — {event_data.get('tool_name', '?')}",
        f": {event_data.get('error_message', 'Unknown error')}",
        style="red",
    )


def render_event_line(event_type: str, event_data: dict[str, Any]) -> ConsoleRenderable:
    """Render a single SSE event as a compact line.

    Args:
        event_type: SSE event type.
        event_data: Parsed event data.

    Returns:
        Rich renderable for the event.
    """
    match event_type:
        case "step.started" | "step_started":
            return render_step_started(event_data)
        case "step.completed" | "step_completed":
            return render_step_completed(event_data)
        case "step.failed" | "step_failed":
            return render_step_failed(event_data)
        case "plan.generated" | "plan_generated":
            return Text("📋 Execution plan generated", style="bold yellow")
        case "plan.awaiting_confirmation":
            return Text("⏳ Awaiting plan confirmation...", style="bold yellow")
        case "execution.completed" | "execution_completed":
            return Text("✓ Execution completed", style="bold green")
        case "execution.failed" | "execution_failed":
            return Text("✖ Execution failed", style="bold red")
        case "execution.cancelled" | "execution_cancelled":
            return Text("⏹ Execution cancelled", style="dim red")
        case "escalation.required" | "escalation_required":
            return Text("⚠ Human intervention required", style="bold magenta")
        case "heartbeat":
            return Text("·", style="dim")
        case _:
            return Text(f"[{event_type}]", style="dim")
