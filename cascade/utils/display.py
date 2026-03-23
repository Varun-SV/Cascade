"""Rich terminal display for Cascade."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree


# ── Colour scheme ───────────────────────────────────────────────────
TIER_COLORS = {
    "t1": "bold magenta",
    "t2": "bold cyan",
    "t3": "bold green",
}

TIER_LABELS = {
    "t1": "🧠 T1 Orchestrator",
    "t2": "🔧 T2 Worker",
    "t3": "⚡ T3 Executor",
}

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
    banner.append("Multi-Tier AI Agent System", style="dim")
    banner.append("     ║\n", style="bold blue")
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


def print_plan(subtasks: list[dict[str, Any]]) -> None:
    """Display the task plan as a tree."""
    tree = Tree("📋 [bold]Execution Plan[/bold]")

    for st in subtasks:
        tier = st.get("assigned_tier", "t2")
        color = TIER_COLORS.get(tier, "white")
        label = TIER_LABELS.get(tier, tier)
        status = st.get("status", "pending")
        icon = STATUS_ICONS.get(status, "⏳")

        branch = tree.add(
            f"{icon} [{color}]{label}[/{color}]: {st.get('description', '')}"
        )
        if st.get("dependencies"):
            branch.add(f"[dim]depends on: {', '.join(st['dependencies'])}[/dim]")

    console.print(tree)
    console.print()


def print_tier_header(tier: str, subtask_desc: str) -> None:
    """Print header when a tier starts working."""
    color = TIER_COLORS.get(tier, "white")
    label = TIER_LABELS.get(tier, tier)
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


def print_escalation(from_tier: str, to_tier: str, reason: str) -> None:
    """Display an escalation event."""
    console.print(
        Panel(
            f"[yellow]Reason: {reason}[/yellow]",
            title=f"⬆️  Escalation: {TIER_LABELS.get(from_tier, from_tier)} → {TIER_LABELS.get(to_tier, to_tier)}",
            border_style="yellow",
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
    table.add_column("Tier", style="bold")
    table.add_column("Cost", justify="right")

    for tier, cost_str in costs.items():
        color = TIER_COLORS.get(tier, "white")
        label = TIER_LABELS.get(tier, tier.upper())
        table.add_row(f"[{color}]{label}[/{color}]", cost_str)

    console.print(table)
