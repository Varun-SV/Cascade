"""Rich terminal display for Cascade."""

from __future__ import annotations

import hashlib
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree


def get_color_for_model(model_id: str) -> str:
    """Generate a consistent rich color based on model ID."""
    # Special defaults for the standard models
    if model_id == "planner": return "bold magenta"
    if model_id == "worker": return "bold cyan"
    if model_id == "local": return "bold green"

    colors = ["magenta", "cyan", "green", "blue", "yellow", "red", "purple"]
    idx = int(hashlib.md5(model_id.encode()).hexdigest(), 16) % len(colors)
    return f"bold {colors[idx]}"


STATUS_ICONS = {
    "pending": "⏳",
    "in_progress": "🔄",
    "completed": "✅",
    "failed": "❌",
    "escalated": "⬆️",
}


console = Console()


def print_banner() -> None:
    """Print the Cascade banner."""
    banner = Text()
    banner.append("╔══════════════════════════════════════╗\n", style="bold blue")
    banner.append("║         ", style="bold blue")
    banner.append("C A S C A D E", style="bold white")
    banner.append("              ║\n", style="bold blue")
    banner.append("║   ", style="bold blue")
    banner.append("Dynamic Fractal Agent System", style="dim")
    banner.append("   ║\n", style="bold blue")
    banner.append("╚══════════════════════════════════════╝", style="bold blue")
    console.print(banner)
    console.print()


def print_task_start(description: str) -> None:
    """Display the start of a new task."""
    console.print(
        Panel(
            description,
            title="[bold white]📋 Task[/bold white]",
            border_style="blue",
            padding=(0, 2),
        )
    )


def print_agent_header(model_id: str, subtask_desc: str) -> None:
    """Print header when an agent starts working or is spawned."""
    color = get_color_for_model(model_id)
    label = f"🤖 {model_id.upper()}"
    console.print(f"\n[{color}]{'━' * 50}[/{color}]")
    console.print(f"[{color}]{label}[/{color}] → {subtask_desc}")
    console.print(f"[{color}]{'━' * 50}[/{color}]")


def print_tool_call(tool_name: str, args: dict[str, Any]) -> None:
    """Display a tool call."""
    args_str = ", ".join(f"{k}={repr(v)[:60]}" for k, v in args.items())
    console.print(f"  🔧 [bold yellow]{tool_name}[/bold yellow]({args_str})")


def print_tool_result(success: bool, output: str, max_lines: int = 10) -> None:
    """Display a tool result (truncated)."""
    lines = output.strip().splitlines()
    if len(lines) > max_lines:
        display = "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"
    else:
        display = output.strip()

    if success:
        console.print(f"  [green]✓[/green] {display[:200]}")
    else:
        console.print(f"  [red]✗ {display[:200]}[/red]")


def print_thinking(text: str) -> None:
    """Display agent thinking/reasoning."""
    if text.strip():
        console.print(f"  [dim italic]💭 {text[:300]}[/dim italic]")


def print_escalation(from_model: str, to_model: str, reason: str) -> None:
    """Display an escalation event."""
    console.print(
        Panel(
            f"[yellow]Reason: {reason}[/yellow]",
            title=f"⬆️  Escalation: {from_model} → {to_model}",
            border_style="yellow",
        )
    )

def print_auditor_block(tool_name: str, reason: str) -> None:
    """Display when the Auditor blocks an action."""
    console.print(
        Panel(
            f"[bold red]Blocked Tool:[/bold red] {tool_name}\n[bold red]Reason:[/bold red] {reason}",
            title="🛡️ [bold red]Auditor Intervention[/bold red]",
            border_style="red",
        )
    )

def print_result(success: bool, summary: str) -> None:
    """Display the final result."""
    if success:
        console.print(
            Panel(
                Markdown(summary),
                title="[bold green]✅ Task Completed[/bold green]",
                border_style="green",
                padding=(1, 2),
            )
        )
    else:
        console.print(
            Panel(
                summary,
                title="[bold red]❌ Task Failed[/bold red]",
                border_style="red",
                padding=(1, 2),
            )
        )


def print_cost_summary(costs: dict[str, str]) -> None:
    """Display cost breakdown."""
    table = Table(title="💰 Cost Summary", show_header=True, border_style="dim")
    table.add_column("Model", style="bold")
    table.add_column("Cost", justify="right")

    for model_id, cost_str in costs.items():
        color = get_color_for_model(model_id)
        table.add_row(f"[{color}]{model_id.upper()}[/{color}]", cost_str)

    console.print(table)
