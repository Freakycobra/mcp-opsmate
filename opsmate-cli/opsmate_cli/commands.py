"""CLI command definitions using Typer.

Provides all opsmate subcommands:
- run: Execute a single command with streaming output
- history: List past executions
- show: Show execution details
- approve: Approve a pending plan
- examples: Show built-in demo commands
- status: Check backend health
- config: Show/edit configuration
- interactive: Start REPL mode
"""

from __future__ import annotations

import asyncio
from typing import Optional
from uuid import UUID

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from opsmate_cli.client import (
    APIClient,
    AuthenticationError,
    ClarificationRequiredError,
    ServerUnavailableError,
    ValidationError,
)
from opsmate_cli.config import get_config, reload_config
from opsmate_cli.models import ExecutionPlan, ExecutionStatus
from opsmate_cli.renderer import (
    ErrorRenderer,
    ExamplesRenderer,
    ExecutionListRenderer,
    FinalOutputRenderer,
    HealthRenderer,
    ModeBadge,
    PlanRenderer,
    SpinnerRenderer,
    render_command_submitted,
    render_escalation,
    render_event_line,
)
from opsmate_cli.interactive import run_interactive_sync

# ── Shared Console ────────────────────────────────────────────────────────────

console = Console()

# ── Helper: Async Runner ──────────────────────────────────────────────────────


def run_async(coro: Any) -> Any:
    """Run an async coroutine from synchronous code.

    Args:
        coro: Coroutine to run.

    Returns:
        Result of the coroutine.
    """
    return asyncio.run(coro)


# ── Command: run ──────────────────────────────────────────────────────────────


def cmd_run(
    command: str = typer.Argument(..., help="Natural language command to execute"),
    auto_approve: bool = typer.Option(
        False, "--auto-approve", "-y",
        help="Skip plan confirmation",
    ),
    mode: Optional[str] = typer.Option(
        None, "--mode",
        help="Override execution mode (mock/live/mixed)",
    ),
    output: str = typer.Option(
        "table", "--output",
        help="Output format: table, json",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Show detailed logs",
    ),
    wait: bool = typer.Option(
        True, "--wait/--no-wait",
        help="Wait for execution to complete",
    ),
) -> None:
    """Execute a single command with streaming output.

    Submits the command to the backend and streams real-time updates.
    Handles plan confirmation interactively if needed.
    """
    config = get_config()
    effective_auto_approve = auto_approve or config.auto_approve
    effective_mode = mode or config.default_mode

    async def _execute() -> None:
        async with APIClient() as client:
            # Submit command
            try:
                response = await client.submit_command(
                    text=command,
                    auto_approve=effective_auto_approve,
                    execution_mode_override=effective_mode,
                )
            except ClarificationRequiredError as e:
                _handle_clarification(e.clarification)
                raise typer.Exit(1)

            console.print(render_command_submitted(response))

            if not wait:
                console.print(f"[dim]Execution started: {response.execution_id}[/dim]")
                return

            # Stream events
            await _stream_execution(
                client=client,
                execution_id=str(response.execution_id),
                verbose=verbose,
                mode=effective_mode,
            )

    try:
        run_async(_execute())
    except typer.Exit:
        raise
    except (AuthenticationError, ServerUnavailableError, ValidationError) as e:
        console.print(ErrorRenderer(e).render())
        raise typer.Exit(1)
    except Exception as e:
        console.print(ErrorRenderer(e).render())
        raise typer.Exit(1)


async def _stream_execution(
    client: APIClient,
    execution_id: str,
    verbose: bool,
    mode: str,
) -> None:
    """Stream execution events and render them.

    Args:
        client: APIClient instance.
        execution_id: Execution UUID.
        verbose: Whether to show verbose output.
        mode: Execution mode string.
    """
    plan_confirmed = False

    try:
        async for event in client.stream_events(execution_id):
            event_type = event.get("event", "message")
            event_data = event.get("data", {})

            if verbose:
                console.print(f"[dim][{event_type}][/dim]")

            match event_type:
                case "plan.awaiting_confirmation":
                    if not plan_confirmed:
                        await _handle_stream_plan_confirmation(
                            client, execution_id, event_data, mode,
                        )
                        plan_confirmed = True

                case "plan.generated" | "plan_generated":
                    if verbose:
                        console.print("[dim]Plan generated[/dim]")

                case "step.started" | "step_started":
                    console.print(render_step_started(event_data))

                case "step.completed" | "step_completed":
                    console.print(render_step_completed(event_data))

                case "step.failed" | "step_failed":
                    console.print(render_step_failed(event_data))

                case "step.skipped" | "step_skipped":
                    step_id = event_data.get("step_id", "?")
                    reason = event_data.get("reason", "")
                    console.print(f"[dim]⊘ {step_id} skipped: {reason}[/dim]")

                case "escalation.required" | "escalation_required":
                    console.print(render_escalation(event_data))

                case "execution.completed" | "execution_completed":
                    console.print("\n[bold green]✓ Execution completed[/bold green]")
                    # Fetch and display final results
                    try:
                        detail = await client.get_execution(execution_id)
                        console.print(FinalOutputRenderer(detail).render())
                    except Exception:
                        pass
                    return

                case "execution.failed" | "execution_failed":
                    console.print("\n[bold red]✖ Execution failed[/bold red]")
                    failure_reason = event_data.get("failure_reason", "")
                    if failure_reason:
                        console.print(f"[red]Reason: {failure_reason}[/red]")
                    raise typer.Exit(1)

                case "execution.cancelled" | "execution_cancelled":
                    console.print("\n[dim red]⏹ Execution cancelled[/dim red]")
                    return

                case "heartbeat":
                    pass

    except ServerUnavailableError as e:
        console.print(f"[dim red]Stream ended: {e}[/dim red]")


async def _handle_stream_plan_confirmation(
    client: APIClient,
    execution_id: str,
    event_data: dict,
    mode: str,
) -> None:
    """Handle plan confirmation during stream.

    Args:
        client: APIClient instance.
        execution_id: Execution UUID.
        event_data: Plan event data.
        mode: Execution mode.
    """
    from opsmate_cli.models import ExecutionPlan, RiskLevel

    try:
        if "plan" in event_data:
            plan = ExecutionPlan.model_validate(event_data["plan"])
        else:
            plan = ExecutionPlan.model_validate(event_data)
    except Exception:
        plan_data = event_data.get("plan", event_data)
        from opsmate_cli.models import PlanStep
        steps_data = plan_data.get("steps", [])
        steps = [PlanStep.model_validate(s) if isinstance(s, dict) else s for s in steps_data]
        deps = plan_data.get("dependencies", {})
        explanation = plan_data.get("explanation", "")
        risk = event_data.get("risk_level", "LOW")
        plan = ExecutionPlan(
            steps=steps,
            dependencies=deps,
            risk_level=RiskLevel(risk),
            explanation=explanation,
        )

    # Render plan
    plan_panel = PlanRenderer(plan, mode).render()
    console.print(plan_panel)

    # Prompt
    answer = typer.prompt(
        "\nApprove this plan? [y]es / [n]o / [m]odify",
        default="y",
        show_default=False,
    ).strip().lower()

    if answer in ("y", "yes", ""):
        await client.approve_plan(execution_id, decision="approve")
        console.print("[green]✓ Plan approved, continuing...[/green]")
    elif answer in ("n", "no"):
        await client.approve_plan(execution_id, decision="reject")
        console.print("[red]✖ Plan rejected.[/red]")
        raise typer.Exit(0)
    elif answer in ("m", "modify"):
        console.print("[yellow]Plan modification not yet supported in CLI.[/yellow]")
        mod_answer = typer.prompt("Approve as-is? [y/n]", default="y").strip().lower()
        if mod_answer in ("y", "yes", ""):
            await client.approve_plan(execution_id, decision="approve")
        else:
            await client.approve_plan(execution_id, decision="reject")
            raise typer.Exit(0)
    else:
        await client.approve_plan(execution_id, decision="approve")


def _handle_clarification(clarification: Any) -> None:
    """Handle clarification required response.

    Args:
        clarification: ClarificationResponse.
    """
    text_parts = [
        "[bold yellow]The command needs clarification.[/bold yellow]\n",
        f"[dim]Confidence: {clarification.confidence:.0%}[/dim]\n",
        f"[yellow]Reason: {clarification.reason}[/yellow]\n",
        "\n[bold]Suggested rephrasings:[/bold]",
        *[f"  • {r}" for r in clarification.suggested_rephrasings],
        "\n[bold]Examples:[/bold]",
        *[f"  • {e}" for e in clarification.examples],
    ]
    console.print(Panel(
        Text.from_markup("\n".join(text_parts)),
        title="[bold yellow]⚠ Clarification Required[/bold yellow]",
        border_style="yellow",
        box=box.ROUNDED,
    ))


def render_step_started(event_data: dict) -> Text:
    """Render step started event line.

    Args:
        event_data: Step started event data.

    Returns:
        Rich Text.
    """
    return Text.assemble(
        ("▶ ", "bold blue"),
        (f"{event_data.get('step_id', '?')}", "bold"),
        f" — {event_data.get('tool_name', '?')}@{event_data.get('server', '?')}",
        style="blue",
    )


def render_step_completed(event_data: dict) -> Text:
    """Render step completed event line.

    Args:
        event_data: Step completed event data.

    Returns:
        Rich Text.
    """
    from opsmate_cli.renderer import format_duration_ms
    duration = event_data.get("duration_ms", 0)
    return Text.assemble(
        ("✓ ", "bold green"),
        (f"{event_data.get('step_id', '?')}", "bold"),
        f" — {event_data.get('tool_name', '?')}  ({format_duration_ms(duration)})",
        style="green",
    )


def render_step_failed(event_data: dict) -> Text:
    """Render step failed event line.

    Args:
        event_data: Step failed event data.

    Returns:
        Rich Text.
    """
    return Text.assemble(
        ("✖ ", "bold red"),
        (f"{event_data.get('step_id', '?')}", "bold"),
        f" — {event_data.get('tool_name', '?')}: {event_data.get('error_message', 'Error')}",
        style="red",
    )


# ── Command: history ──────────────────────────────────────────────────────────


def cmd_history(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of results"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    page: int = typer.Option(1, "--page", "-p", help="Page number"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Auto-refresh (not implemented)"),
) -> None:
    """List past executions."""
    if watch:
        console.print("[yellow]Watch mode: press Ctrl+C to stop[/yellow]\n")

    async def _list() -> None:
        async with APIClient() as client:
            response = await client.list_executions(
                page=page,
                page_size=limit,
                status=status,
            )
            table = ExecutionListRenderer(response).render()
            console.print(table)

    try:
        run_async(_list())
    except Exception as e:
        console.print(ErrorRenderer(e).render())
        raise typer.Exit(1)


# ── Command: show ─────────────────────────────────────────────────────────────


def cmd_show(
    execution_id: str = typer.Argument(..., help="Execution UUID"),
) -> None:
    """Show execution details."""
    async def _show() -> None:
        async with APIClient() as client:
            detail = await client.get_execution(execution_id)
            console.print(FinalOutputRenderer(detail).render())

            # Show plan if available
            if detail.plan:
                console.print(PlanRenderer(detail.plan, detail.execution_mode).render())

    try:
        run_async(_show())
    except Exception as e:
        console.print(ErrorRenderer(e).render())
        raise typer.Exit(1)


# ── Command: approve ──────────────────────────────────────────────────────────


def cmd_approve(
    execution_id: str = typer.Argument(..., help="Execution UUID"),
    decision: str = typer.Option("approve", "--decision", "-d", help="Decision: approve/reject/modify"),
    reason: Optional[str] = typer.Option(None, "--reason", "-r", help="Reason for rejection/modification"),
) -> None:
    """Approve a pending execution plan."""
    async def _approve() -> None:
        async with APIClient() as client:
            result = await client.approve_plan(execution_id, decision=decision, reason=reason)
            status_color = {
                "completed": "green",
                "executing": "blue",
                "cancelled": "red",
            }.get(result.new_status.value, "white")

            console.print(Panel(
                Text.assemble(
                    ("Decision: ", "bold"), (result.decision, "bold"), "\n",
                    ("New Status: ", "bold"), (result.new_status.value.upper(), f"bold {status_color}"), "\n",
                    (result.message, "dim"),
                ),
                title=f"[bold]Execution {str(result.execution_id)[:8]}...[/bold]",
                border_style=status_color,
                box=box.ROUNDED,
            ))

    try:
        run_async(_approve())
    except Exception as e:
        console.print(ErrorRenderer(e).render())
        raise typer.Exit(1)


# ── Command: examples ─────────────────────────────────────────────────────────


def cmd_examples() -> None:
    """Show built-in demo commands."""
    async def _examples() -> None:
        async with APIClient() as client:
            response = await client.get_examples()
            table = ExamplesRenderer(response.examples).render()
            console.print(table)

    try:
        run_async(_examples())
    except Exception as e:
        console.print(ErrorRenderer(e).render())
        raise typer.Exit(1)


# ── Command: status ───────────────────────────────────────────────────────────


def cmd_status(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full details"),
) -> None:
    """Check backend health."""
    async def _status() -> None:
        async with APIClient() as client:
            health = await client.health_check()
            console.print(HealthRenderer(health).render())

            if verbose:
                console.print(f"\n[dim]Version: {health.version}[/dim]")
                console.print(f"[dim]Uptime: {health.uptime_seconds:.0f}s[/dim]")

    try:
        run_async(_status())
    except Exception as e:
        console.print(ErrorRenderer(e).render())
        raise typer.Exit(1)


# ── Command: config ───────────────────────────────────────────────────────────


config_app = typer.Typer(help="Show and edit configuration", no_args_is_help=True)


def cmd_config_show() -> None:
    """Show current configuration."""
    config = get_config()
    table = table = Table(show_header=True, header_style="bold", box=box.SIMPLE_HEAVY)
    table.add_column("Section", style="bold")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="bold")

    for section, key, value in config.as_table_data():
        table.add_row(section, key, str(value))

    console.print(table)

    # Show config file location
    if config.config_file.exists():
        console.print(f"\n[dim]Config file: {config.config_file}[/dim]")
    else:
        console.print(f"\n[dim]Config file: {config.config_file} (not yet created)[/dim]")


def cmd_config_set(
    key: str = typer.Argument(..., help="Configuration key to set"),
    value: str = typer.Argument(..., help="Value to set"),
) -> None:
    """Set a configuration value."""
    config = get_config()

    try:
        config.set(key, value)
        config.save_to_file()
        console.print(f"[green]✓ Set {key} = {value}[/green]")
        console.print(f"[dim]Saved to {config.config_file}[/dim]")
    except AttributeError as e:
        console.print(f"[red]✖ {e}[/red]")
        raise typer.Exit(1)


def cmd_config_get(
    key: str = typer.Argument(..., help="Configuration key to get"),
) -> None:
    """Get a configuration value."""
    config = get_config()

    if not hasattr(config, key):
        console.print(f"[red]✖ Unknown config key: {key}[/red]")
        console.print(f"[dim]Available keys: api_url, api_key, timeout, theme, output_format, auto_approve, default_mode, ...[/dim]")
        raise typer.Exit(1)

    value = getattr(config, key)
    # Mask sensitive values
    if "key" in key.lower() or "token" in key.lower() or "secret" in key.lower():
        value = "***" if value else "(not set)"

    console.print(f"[bold]{key}[/bold] = {value}")


def cmd_config_reload() -> None:
    """Reload configuration from file."""
    config = reload_config()
    console.print(f"[green]✓ Configuration reloaded from {config.config_file}[/green]")


# ── Command: interactive ──────────────────────────────────────────────────────


def cmd_interactive() -> None:
    """Start interactive REPL mode."""
    run_interactive_sync(console=console)


