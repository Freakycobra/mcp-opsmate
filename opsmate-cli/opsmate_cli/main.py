"""Entry point for the OpsMate CLI.

Registers all Typer commands and provides global options like --version.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from opsmate_cli import __version__
from opsmate_cli.commands import (
    cmd_approve,
    cmd_config_get,
    cmd_config_reload,
    cmd_config_set,
    cmd_config_show,
    cmd_examples,
    cmd_history,
    cmd_interactive,
    cmd_run,
    cmd_show,
    cmd_status,
)
from opsmate_cli.config import get_config

# ── Console ───────────────────────────────────────────────────────────────────

console = Console()

# ── Typer App ─────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="opsmate",
    help="OpsMate CLI — Infrastructure Automation Terminal",
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)


# ── Global Callback ───────────────────────────────────────────────────────────


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-V",
        help="Show version and exit.",
        is_eager=True,
    ),
    api_url: Optional[str] = typer.Option(
        None, "--api-url", "-u",
        help="Override API base URL.",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k",
        help="Override API key.",
    ),
    config_file: Optional[Path] = typer.Option(
        None, "--config", "-c",
        help="Path to config file.",
        exists=False,
    ),
) -> None:
    """OpsMate CLI — Infrastructure Automation Terminal.

    Communicates with the FastAPI backend to execute infrastructure commands
    via natural language. Supports streaming execution, plan confirmation,
    and interactive REPL mode.
    """
    if version:
        _print_version()
        raise typer.Exit()

    # Apply global overrides to config
    config = get_config()
    if api_url:
        config.api_url = api_url
    if api_key:
        config.api_key = api_key
    if config_file:
        config.config_file = config_file


def _print_version() -> None:
    """Print version information."""
    version_text = Text.assemble(
        ("OpsMate CLI", "bold"), " v", (__version__, "bold cyan"), "\n",
        "Infrastructure Automation Terminal\n\n",
        ("API: ", "dim"), (f"{get_config().api_url}\n", "bold"),
        ("Config: ", "dim"), (f"{get_config().config_file}\n", "bold"),
    )
    console.print(version_text)


# ── Register Commands ─────────────────────────────────────────────────────────

@app.command("run")
def run(
    command: str = typer.Argument(..., help="Natural language command to execute"),
    auto_approve: bool = typer.Option(False, "--auto-approve", "-y", help="Skip plan confirmation"),
    mode: Optional[str] = typer.Option(None, "--mode", help="Override execution mode (mock/live/mixed)"),
    output: str = typer.Option("table", "--output", help="Output format: table, json"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed logs"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for execution to complete"),
) -> None:
    """Execute a single command with streaming output."""
    cmd_run(
        command=command,
        auto_approve=auto_approve,
        mode=mode,
        output=output,
        verbose=verbose,
        wait=wait,
    )


@app.command("history")
def history(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of results"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    page: int = typer.Option(1, "--page", "-p", help="Page number"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Auto-refresh"),
) -> None:
    """List past executions."""
    cmd_history(limit=limit, status=status, page=page, watch=watch)


@app.command("show")
def show(
    execution_id: str = typer.Argument(..., help="Execution UUID"),
) -> None:
    """Show execution details."""
    cmd_show(execution_id=execution_id)


@app.command("approve")
def approve(
    execution_id: str = typer.Argument(..., help="Execution UUID"),
    decision: str = typer.Option("approve", "--decision", "-d", help="Decision: approve/reject/modify"),
    reason: Optional[str] = typer.Option(None, "--reason", "-r", help="Reason for rejection"),
) -> None:
    """Approve a pending execution plan."""
    cmd_approve(execution_id=execution_id, decision=decision, reason=reason)


@app.command("examples")
def examples() -> None:
    """Show built-in demo commands."""
    cmd_examples()


@app.command("status")
def status(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full details"),
) -> None:
    """Check backend health."""
    cmd_status(verbose=verbose)


# ── Config Subcommand ─────────────────────────────────────────────────────────

config_app = typer.Typer(help="Show and edit configuration", no_args_is_help=True)
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    """Show current configuration."""
    cmd_config_show()


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Configuration key to set"),
    value: str = typer.Argument(..., help="Value to set"),
) -> None:
    """Set a configuration value."""
    cmd_config_set(key=key, value=value)


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Configuration key to get"),
) -> None:
    """Get a configuration value."""
    cmd_config_get(key=key)


@config_app.command("reload")
def config_reload() -> None:
    """Reload configuration from file."""
    cmd_config_reload()


# ── Interactive Command ───────────────────────────────────────────────────────

@app.command("interactive")
def interactive() -> None:
    """Start interactive REPL mode."""
    cmd_interactive()


# ── Entry Point ───────────────────────────────────────────────────────────────


def entrypoint() -> None:
    """CLI entrypoint with error handling."""
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/dim]")
        sys.exit(130)
    except BrokenPipeError:
        # Handle piped output being closed
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]Unexpected error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    entrypoint()
