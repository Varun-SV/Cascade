"""Rich terminal display for Cascade."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from rich.syntax import Syntax
from rich.padding import Padding
from rich import box

console = Console()

def get_color_for_model(model_id: str) -> str:
    """Generate a consistent rich color based on model ID."""
    if model_id == "planner": return "magenta"
    if model_id == "worker": return "cyan"
    if model_id == "local": return "green"

    colors = ["magenta", "cyan", "green", "blue", "yellow", "red", "purple"]
    idx = int(hashlib.md5(model_id.encode()).hexdigest(), 16) % len(colors)
    return colors[idx]


def print_banner() -> None:
    """Print the Cascade banner."""
    title = Text(" 🌊 C A S C A D E ", style="bold white on dodger_blue2")
    subtitle = Text("Dynamic Fractal AI Agent System", style="dim italic")
    group = Group(title, subtitle)
    console.print(Panel(group, border_style="dodger_blue2", box=box.DOUBLE_EDGE, expand=False, padding=(1, 4)))
    console.print()


def print_task_start(description: str) -> None:
    """Display the start of a new task."""
    console.print(
        Panel(
            Text(description, style="bold white"),
            title="[bold dodger_blue1]🎯 Primary Objective[/bold dodger_blue1]",
            border_style="dodger_blue1",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )
    console.print()


def print_agent_header(model_id: str, subtask_desc: str) -> None:
    """Print header when an agent starts working or is spawned."""
    color = get_color_for_model(model_id)
    console.print()
    console.print(Rule(title=f"🧠 [bold {color}]{model_id.upper()}[/bold {color}]", style=color))
    console.print(Padding(f"[italic]{subtask_desc}[/italic]", (0, 0, 1, 4)))


def print_tool_call(tool_name: str, args: dict[str, Any]) -> None:
    """Display a tool call."""
    
    # Hide massive prompt payload for delegate_task so terminal remains clean
    display_args = args.copy()
    if tool_name == "delegate_task" and "description" in display_args:
        display_args["description"] = "<hidden to preserve console readability>"
        
    # Format arguments as compact JSON syntax highlighting
    try:
        args_json = json.dumps(display_args, indent=2)
    except TypeError:
        args_json = str(display_args)
    
    # If it's a massive arg (like writing a whole file), truncate visual
    if len(args_json) > 1000:
        args_json = args_json[:1000] + "\n... (truncated visual)"
        
    syntax = Syntax(args_json, "json", theme="monokai", padding=0, word_wrap=True)
    
    panel = Panel(
        syntax,
        title=f"🔧 [bold yellow]{tool_name}[/bold yellow]",
        title_align="left",
        border_style="yellow",
        box=box.ROUNDED,
        padding=(0, 1)
    )
    console.print(Padding(panel, (0, 0, 0, 4)))


def print_tool_result(success: bool, output: str, max_lines: int = 15) -> None:
    """Display a tool result (truncated)."""
    lines = output.strip().splitlines()
    if len(lines) > max_lines:
        display_text = "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"
    else:
        display_text = output.strip()

    if not display_text:
        display_text = "(Success with no output)"

    if success:
        # Subtle dim formatting for success so it doesn't overwhelm the logs
        text = Text(display_text, style="dim green")
        console.print(Padding(text, (0, 0, 1, 6)))
    else:
        # Bright red panel for failures
        panel = Panel(
            Text(display_text, style="red"),
            title="[bold red]❌ Execution Error[/bold red]",
            border_style="red",
            box=box.ROUNDED,
            title_align="left",
            padding=(0, 1)
        )
        console.print(Padding(panel, (0, 0, 1, 4)))


def print_thinking(text: str) -> None:
    """Display agent thinking/reasoning."""
    if not text.strip():
        return
    # Use a subtle left-border panel for thinking
    panel = Panel(
        Text(text.strip(), style="dim white"),
        border_style="dim",
        box=box.MINIMAL,
        title="💭 [dim]Thinking...[/dim]",
        title_align="left",
    )
    console.print(Padding(panel, (0, 0, 0, 2)))


def print_escalation(from_model: str, to_model: str, reason: str) -> None:
    """Display an escalation event."""
    console.print()
    console.print(
        Padding(
            Panel(
                f"[bold orange3]{reason}[/bold orange3]",
                title=f"⚠️ [bold orange3]Escalating: {from_model.upper()} → {to_model.upper()}[/bold orange3]",
                border_style="orange3",
                box=box.HEAVY,
            ),
            (0, 0, 0, 4)
        )
    )


def print_auditor_block(tool_name: str, reason: str) -> None:
    """Display when the Auditor blocks an action."""
    console.print(
        Padding(
            Panel(
                f"[bold red]Blocked Tool:[/bold red] {tool_name}\n[bold red]Reason:[/bold red] {reason}",
                title="🛡️ [bold red]Sentinel Auditor Intervention[/bold red]",
                border_style="red",
                box=box.DOUBLE,
            ),
            (0, 0, 0, 4)
        )
    )


def print_result(success: bool, summary: str) -> None:
    """Display the final result."""
    console.print()
    
    # Clean up empty or overly generic summaries
    display_summary = summary.strip() if summary else ""
    if not display_summary:
        display_summary = "Task completed. No detailed summary was provided by the agent."
    
    if success:
        console.print(
            Panel(
                Markdown(display_summary),
                title="✨ [bold green]Task Completed Successfully[/bold green] ✨",
                border_style="green",
                box=box.DOUBLE,
                padding=(1, 2),
            )
        )
    else:
        console.print(
            Panel(
                Markdown(display_summary),
                title="💥 [bold red]Task Failed[/bold red] 💥",
                border_style="red",
                box=box.DOUBLE,
                padding=(1, 2),
            )
        )


def print_cost_summary(costs: dict[str, str]) -> None:
    """Display cost breakdown."""
    table = Table(title="💎 Resource Usage", show_header=True, border_style="dim", box=box.ROUNDED)
    table.add_column("Agent Model", style="bold")
    table.add_column("Est. Cost", justify="right", style="green")

    for model_id, cost_str in costs.items():
        color = get_color_for_model(model_id)
        table.add_row(f"[{color}]{model_id.upper()}[/{color}]", cost_str)

    console.print(table)
    console.print()
