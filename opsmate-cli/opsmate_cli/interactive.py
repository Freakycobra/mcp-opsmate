"""Interactive mode (REPL-like) for the OpsMate CLI.

Provides a continuous prompt with:
- Command history (up/down arrow recall)
- Tab completion for service names, time patterns, severity levels
- Streaming output as execution runs
- Plan confirmation mid-stream
- Graceful Ctrl+C handling
- Built-in commands: exit, history, examples, mode, status
"""

from __future__ import annotations

import asyncio
import atexit
import signal
import sys
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion, WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts import confirm
from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from opsmate_cli.client import (
    APIClient,
    AuthenticationError,
    ClarificationRequiredError,
    ServerUnavailableError,
    ValidationError,
)
from opsmate_cli.config import get_config
from opsmate_cli.renderer import (
    ErrorRenderer,
    ExamplesRenderer,
    ExecutionListRenderer,
    HealthRenderer,
    PlanRenderer,
    render_command_submitted,
    render_escalation,
    render_event_line,
    render_plan_confirmation,
)

# ── Constants ─────────────────────────────────────────────────────────────────

PROMPT_STYLE = "bold cyan"
PROMPT_TEXT = "opsmate> "

BUILTIN_COMMANDS = ["exit", "quit", "history", "examples", "mode", "status", "help", "clear"]

COMPLETION_WORDS = [
    # Service names (common)
    "payment-service", "user-service", "order-service", "notification-service",
    "auth-service", "inventory-service", "shipping-service", "cart-service",
    "product-service", "search-service", "recommendation-service",
    # Time patterns
    "last 1h", "last 2h", "last 5h", "last 12h", "last 24h",
    "last 1d", "last 2d", "last 7d", "last 30d",
    "since yesterday", "since last week", "since last month",
    # Severity levels
    "critical", "error", "warning", "info", "debug",
    # Common command verbs
    "check health of", "restart", "scale", "deploy", "rollback",
    "describe pods for", "check logs for", "check status of",
    "compare performance of", "analyze costs for",
    # Built-in commands
    *BUILTIN_COMMANDS,
]

# ── Custom Completer ──────────────────────────────────────────────────────────


class OpsmateCompleter(Completer):
    """Custom completer for the OpsMate interactive prompt."""

    def __init__(self) -> None:
        self._word_completer = WordCompleter(COMPLETION_WORDS, ignore_case=True, match_middle=True)

    def get_completions(self, document, complete_event):
        yield from self._word_completer.get_completions(document, complete_event)


# ── Interactive Session ───────────────────────────────────────────────────────


class InteractiveSession:
    """Interactive REPL session for OpsMate.

    Manages the prompt session, streaming execution output,
    plan confirmation, and graceful cancellation.
    """

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self.config = get_config()

        # Prompt session with history
        history_file = self.config.history_file
        history_file.parent.mkdir(parents=True, exist_ok=True)

        self.session: PromptSession[str] = PromptSession(
            PROMPT_TEXT,
            history=FileHistory(str(history_file)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=OpsmateCompleter(),
            enable_history_search=True,
        )

        # Execution state
        self._current_execution_id: str | None = None
        self._cancelled: bool = False
        self._shutdown: bool = False

        # Setup signal handlers for graceful Ctrl+C
        self._setup_signals()

        # Register cleanup on exit
        atexit.register(self._cleanup)

    def _setup_signals(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        try:
            # Windows doesn't support SIGINT the same way
            signal.signal(signal.SIGINT, self._signal_handler)
        except (ValueError, OSError):
            pass

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle Ctrl+C by cancelling current execution."""
        if self._current_execution_id:
            self._cancelled = True
            self.console.print("\n[yellow]Cancelling current execution...[/yellow]")
        else:
            self._shutdown = True
            self.console.print("\n[yellow]Use 'exit' or Ctrl+D to quit.[/yellow]")

    def _cleanup(self) -> None:
        """Cleanup resources on exit."""
        pass  # FileHistory handles its own cleanup

    # ── Main Loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Run the interactive REPL loop."""
        self._print_welcome()

        while not self._shutdown:
            try:
                user_input = await self.session.prompt_async()
                user_input = user_input.strip()

                if not user_input:
                    continue

                await self._handle_input(user_input)

            except (EOFError, KeyboardInterrupt):
                # Ctrl+D or Ctrl+C at empty prompt -> exit
                self.console.print("\n[dim]Goodbye![/dim]")
                break

        self._shutdown = True

    def _print_welcome(self) -> None:
        """Print welcome banner."""
        from opsmate_cli import __version__

        banner = Panel(
            Text.assemble(
                ("OpsMate CLI v", "bold"),
                (__version__, "bold cyan"),
                "\n",
                "Infrastructure Automation Terminal",
                "\n\n",
                ("Type ", "dim"),
                ("'help'", "bold green"),
                (" for available commands, ", "dim"),
                ("'exit'", "bold red"),
                (" to quit.", "dim"),
                "\n",
                (f"API: {self.config.api_url}", "dim"),
                "  ",
                (f"Mode: {self.config.default_mode.upper()}", "bold"),
            ),
            title="[bold]Welcome[/bold]",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
        self.console.print(banner)

    async def _handle_input(self, user_input: str) -> None:
        """Handle a single user input.

        Args:
            user_input: The user's input string.
        """
        # Check for built-in commands
        cmd_lower = user_input.lower()

        if cmd_lower in ("exit", "quit"):
            self.console.print("[dim]Goodbye![/dim]")
            self._shutdown = True
            return

        if cmd_lower == "help":
            self._print_help()
            return

        if cmd_lower == "clear":
            self.console.clear()
            return

        if cmd_lower == "history":
            await self._show_history()
            return

        if cmd_lower == "examples":
            await self._show_examples()
            return

        if cmd_lower == "mode":
            self._show_mode()
            return

        if cmd_lower == "status":
            await self._show_status()
            return

        # Treat as a command to execute
        await self._execute_command(user_input)

    def _print_help(self) -> None:
        """Print help text for interactive commands."""
        help_text = Text.assemble(
            ("Interactive Commands:\n\n", "bold underline"),
            ("  exit, quit    ", "bold green"), "Exit the interactive session\n",
            ("  help          ", "bold green"), "Show this help message\n",
            ("  clear         ", "bold green"), "Clear the screen\n",
            ("  history       ", "bold green"), "Show past executions\n",
            ("  examples      ", "bold green"), "Show example commands\n",
            ("  mode          ", "bold green"), "Show current execution mode\n",
            ("  status        ", "bold green"), "Check backend health\n",
            "\n",
            ("Any other text is treated as a command to execute.\n", "dim"),
            ("Use Up/Down arrows for history, Tab for completion.", "dim"),
        )
        self.console.print(Panel(help_text, border_style="cyan", box=box.ROUNDED))

    # ── Built-in Commands ─────────────────────────────────────────────────────

    async def _show_history(self) -> None:
        """Show past executions."""
        try:
            async with APIClient() as client:
                response = await client.list_executions(
                    page=1,
                    page_size=self.config.history_limit,
                )
                table = ExecutionListRenderer(response).render()
                self.console.print(table)
        except Exception as e:
            self.console.print(ErrorRenderer(e).render())

    async def _show_examples(self) -> None:
        """Show built-in demo commands."""
        try:
            async with APIClient() as client:
                examples = await client.get_examples()
                table = ExamplesRenderer(examples.examples).render()
                self.console.print(table)
        except Exception as e:
            self.console.print(ErrorRenderer(e).render())

    def _show_mode(self) -> None:
        """Show current execution mode."""
        from opsmate_cli.renderer import MODE_COLORS, ModeBadge
        from opsmate_cli.models import ExecutionMode

        mode = ExecutionMode(self.config.default_mode)
        badge = ModeBadge(mode).__rich__()

        self.console.print(Panel(
            Text.assemble("Current mode: ", badge),
            title="[bold]Execution Mode[/bold]",
            border_style=MODE_COLORS.get(mode, "white"),
            box=box.ROUNDED,
        ))

    async def _show_status(self) -> None:
        """Check backend health."""
        try:
            async with APIClient() as client:
                health = await client.health_check()
                self.console.print(HealthRenderer(health).render())
        except Exception as e:
            self.console.print(ErrorRenderer(e).render())

    # ── Command Execution ─────────────────────────────────────────────────────

    async def _execute_command(self, command_text: str) -> None:
        """Execute a natural language command with streaming output.

        Handles the full lifecycle:
        1. Submit command to backend
        2. Stream SSE events
        3. Handle plan confirmation mid-stream
        4. Render results in real-time
        5. Handle cancellation gracefully

        Args:
            command_text: Natural language command.
        """
        self._cancelled = False
        self._current_execution_id = None

        # Auto-approve from config or command
        auto_approve = self.config.auto_approve

        try:
            async with APIClient() as client:
                # Step 1: Submit command
                try:
                    response = await client.submit_command(
                        text=command_text,
                        auto_approve=auto_approve,
                        execution_mode_override=self.config.default_mode,
                    )
                except ClarificationRequiredError as e:
                    self._handle_clarification(e.clarification)
                    return

                self._current_execution_id = str(response.execution_id)
                self.console.print(render_command_submitted(response))

                # Step 2: Stream events
                await self._stream_execution(client, str(response.execution_id))

        except AuthenticationError as e:
            self.console.print(ErrorRenderer(e).render())
        except ServerUnavailableError as e:
            self.console.print(ErrorRenderer(e).render())
        except ValidationError as e:
            self.console.print(ErrorRenderer(e).render())
        except Exception as e:
            self.console.print(ErrorRenderer(e).render())
        finally:
            self._current_execution_id = None
            self._cancelled = False

    async def _stream_execution(self, client: APIClient, execution_id: str) -> None:
        """Stream SSE events for an execution.

        Args:
            client: APIClient instance.
            execution_id: Execution UUID.
        """
        pending_events: list[Text] = []

        with Live(
            Text("Connecting to stream...", style="dim"),
            console=self.console,
            refresh_per_second=8,
            transient=False,
        ) as live:
            try:
                async for event in client.stream_events(execution_id):
                    if self._cancelled:
                        live.update(Text("Execution cancelled by user.", style="yellow"))
                        return

                    event_type = event.get("event", "message")
                    event_data = event.get("data", {})

                    match event_type:
                        case "plan.awaiting_confirmation" | "plan_generated" | "plan.generated":
                            # Plan generated — may need confirmation
                            await self._handle_plan_confirmation(
                                client, execution_id, event_data, live, pending_events,
                            )

                        case "step.started" | "step_started":
                            line = render_step_started(event_data)
                            pending_events.append(line)
                            live.update(self._build_event_list(pending_events))

                        case "step.completed" | "step_completed":
                            line = render_step_completed(event_data)
                            if pending_events and pending_events[-1].plain.startswith("▶"):
                                # Replace the "started" line with "completed"
                                pending_events[-1] = line
                            else:
                                pending_events.append(line)
                            live.update(self._build_event_list(pending_events))

                        case "step.failed" | "step_failed":
                            line = render_step_failed(event_data)
                            if pending_events and pending_events[-1].plain.startswith("▶"):
                                pending_events[-1] = line
                            else:
                                pending_events.append(line)
                            live.update(self._build_event_list(pending_events))

                        case "escalation.required" | "escalation_required":
                            self.console.print(render_escalation(event_data))
                            pending_events.append(Text("⚠ Escalation — waiting for resolution", style="magenta"))
                            live.update(self._build_event_list(pending_events))

                        case "execution.completed" | "execution_completed":
                            pending_events.append(Text("\n✓ Execution completed", style="bold green"))
                            live.update(self._build_event_list(pending_events))

                        case "execution.failed" | "execution_failed":
                            pending_events.append(Text("\n✖ Execution failed", style="bold red"))
                            failure_reason = event_data.get("failure_reason", "")
                            if failure_reason:
                                pending_events.append(Text(f"  Reason: {failure_reason}", style="red"))
                            live.update(self._build_event_list(pending_events))

                        case "execution.cancelled" | "execution_cancelled":
                            pending_events.append(Text("\n⏹ Execution cancelled", style="dim red"))
                            live.update(self._build_event_list(pending_events))

                        case "heartbeat":
                            # Ignore heartbeats for display
                            pass

                        case _:
                            # Unknown event type — show minimally
                            pass

            except ServerUnavailableError as e:
                live.update(Text(f"Stream ended: {e}", style="dim red"))
            except Exception as e:
                live.update(Text(f"Stream error: {e}", style="dim red"))

    def _build_event_list(self, events: list[Text]) -> Text:
        """Build display text from list of events.

        Args:
            events: List of event Text objects.

        Returns:
            Combined Text with last N events.
        """
        # Keep last 20 events to avoid overwhelming the display
        recent = events[-20:]
        return Text("\n").join(recent)

    async def _handle_plan_confirmation(
        self,
        client: APIClient,
        execution_id: str,
        event_data: dict[str, Any],
        live: Live,
        pending_events: list[Text],
    ) -> None:
        """Handle plan confirmation mid-stream.

        Pauses the stream, displays the plan, and prompts for approval.

        Args:
            client: APIClient instance.
            execution_id: Execution UUID.
            event_data: Plan event data.
            live: Rich Live display.
            pending_events: Accumulated event lines.
        """
        from opsmate_cli.models import ExecutionPlan, RiskLevel

        # Parse plan from event data
        plan_data = event_data.get("plan", event_data)
        risk_level = event_data.get("risk_level", "LOW")

        try:
            if "plan" in event_data:
                plan = ExecutionPlan.model_validate(event_data["plan"])
            else:
                plan = ExecutionPlan.model_validate(event_data)
        except Exception:
            # If plan parsing fails, try to construct from whatever we got
            steps_data = plan_data.get("steps", [])
            from opsmate_cli.models import PlanStep
            steps = [PlanStep.model_validate(s) if isinstance(s, dict) else s for s in steps_data]
            deps = plan_data.get("dependencies", {})
            explanation = plan_data.get("explanation", "")
            plan = ExecutionPlan(
                steps=steps,
                dependencies=deps,
                risk_level=RiskLevel(risk_level),
                explanation=explanation,
            )

        # Show the plan
        plan_panel = PlanRenderer(plan, get_config().default_mode).render()
        self.console.print(plan_panel)

        # Prompt for confirmation
        prompt_text = Text.assemble(
            "\nApprove this plan? ",
            ("[y]", "bold green"),
            "es / ",
            ("[n]", "bold red"),
            "o / ",
            ("[m]", "bold yellow"),
            "odify: ",
        )
        self.console.print(prompt_text)

        try:
            answer = await self.session.prompt_async("")
            answer = answer.strip().lower()

            if answer in ("y", "yes"):
                await client.approve_plan(execution_id, decision="approve")
                self.console.print("[green]✓ Plan approved, continuing execution...[/green]")
                pending_events.append(Text("✓ Plan approved", style="green"))

            elif answer in ("n", "no"):
                await client.approve_plan(execution_id, decision="reject")
                self.console.print("[red]✖ Plan rejected, execution cancelled.[/red]")
                pending_events.append(Text("✖ Plan rejected", style="red"))
                self._cancelled = True

            elif answer in ("m", "modify"):
                self.console.print("[yellow]Plan modification not yet supported. Approve as-is? [y/n]:[/yellow]")
                retry = await self.session.prompt_async("")
                if retry.strip().lower() in ("y", "yes"):
                    await client.approve_plan(execution_id, decision="approve")
                    pending_events.append(Text("✓ Plan approved (unmodified)", style="green"))
                else:
                    await client.approve_plan(execution_id, decision="reject")
                    self._cancelled = True
                    pending_events.append(Text("✖ Plan rejected", style="red"))
            else:
                # Default to approve on empty/unrecognized
                await client.approve_plan(execution_id, decision="approve")
                pending_events.append(Text("✓ Plan approved (default)", style="green"))

        except (EOFError, KeyboardInterrupt):
            # Ctrl+C during confirmation -> reject
            self.console.print("\n[red]✖ Plan rejected (interrupted).[/red]")
            try:
                await client.approve_plan(execution_id, decision="reject")
            except Exception:
                pass
            self._cancelled = True
            pending_events.append(Text("✖ Plan rejected", style="red"))

    def _handle_clarification(self, clarification: Any) -> None:
        """Handle clarification required response.

        Args:
            clarification: ClarificationResponse.
        """
        panel = Panel(
            Text.assemble(
                ("The command needs clarification.\n\n", "bold yellow"),
                (f"Confidence: {clarification.confidence:.0%}\n", "dim"),
                (f"Reason: {clarification.reason}\n\n", "yellow"),
                ("Suggested rephrasings:\n", "bold"),
                *(f"  • {r}\n" for r in clarification.suggested_rephrasings),
                "\n",
                ("Examples:\n", "bold"),
                *(f"  • {e}\n" for e in clarification.examples),
            ),
            title="[bold yellow]⚠ Clarification Required[/bold yellow]",
            border_style="yellow",
            box=box.HEAVY,
        )
        self.console.print(panel)


# ── Public API ────────────────────────────────────────────────────────────────


async def run_interactive(console: Console | None = None) -> None:
    """Run the interactive REPL session.

    Args:
        console: Optional Rich Console instance.
    """
    session = InteractiveSession(console=console)
    await session.run()


def run_interactive_sync(console: Console | None = None) -> None:
    """Run the interactive REPL session (synchronous wrapper).

    Args:
        console: Optional Rich Console instance.
    """
    try:
        asyncio.run(run_interactive(console))
    except KeyboardInterrupt:
        Console().print("\n[dim]Goodbye![/dim]")
