"""Cascade CLI — command-line interface."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from cascade import __version__

app = typer.Typer(
    name="cascade",
    help="🌊 Cascade — Multi-Tier AI Agent Orchestration System",
    add_completion=False,
    pretty_exceptions_show_locals=False,
)
console = Console()


@app.command()
def run(
    task: str = typer.Argument(..., help="Task description — what should Cascade do?"),
    config: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to config YAML file"
    ),
    project_root: Optional[str] = typer.Option(
        None, "--root", "-r", help="Project root directory"
    ),
    budget: Optional[float] = typer.Option(
        None, "--budget", "-b", help="Max session cost in dollars"
    ),
    tier: Optional[str] = typer.Option(
        None, "--tier", "-t", help="Force a specific tier (t1, t2, t3)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Execute a task using the Cascade multi-tier agent system."""
    from cascade.api import Cascade
    from cascade.config import load_config
    from cascade.utils.display import (
        print_banner,
        print_cost_summary,
        print_escalation,
        print_plan,
        print_result,
        print_task_start,
        print_tier_header,
        print_thinking,
        print_tool_call,
    )

    print_banner()
    print_task_start(task)

    # Load config and apply CLI overrides
    cfg = load_config(config)
    if verbose:
        cfg.verbose = True
    if budget is not None:
        cfg.budget.enabled = True
        cfg.budget.session_max_cost = budget

    # Create agent
    agent = Cascade(
        config=cfg,
        project_root=project_root or ".",
    )

    # Wire up display callbacks
    async def on_plan(plan):
        subtask_dicts = [
            {
                "description": st.description,
                "assigned_tier": st.assigned_tier.value,
                "status": st.status.value,
                "dependencies": st.dependencies,
            }
            for st in plan.subtasks
        ]
        print_plan(subtask_dicts)

    async def on_tier_start(tier_name, desc):
        print_tier_header(tier_name, desc)

    async def on_tool_call_cb(name, args):
        print_tool_call(name, args)

    async def on_thinking_cb(text):
        print_thinking(text)

    async def on_escalation_cb(from_t, to_t, reason):
        print_escalation(from_t, to_t, reason)

    agent.on_plan = on_plan
    agent.on_tier_start = on_tier_start
    agent.on_tool_call = on_tool_call_cb
    agent.on_thinking = on_thinking_cb
    agent.on_escalation = on_escalation_cb

    # Execute
    try:
        result = asyncio.run(agent.run_async(task))
        console.print()
        print_result(result.success, result.summary)
        print_cost_summary(agent.cost_tracker.get_summary())
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled by user.[/yellow]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        if verbose:
            console.print_exception()
        raise typer.Exit(1)


@app.command()
def models(
    config: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to config YAML file"
    ),
) -> None:
    """List available models for each configured provider."""
    from cascade.api import Cascade
    from cascade.config import load_config

    cfg = load_config(config)
    agent = Cascade(config=cfg)

    async def _list():
        return await agent.list_models()

    all_models = asyncio.run(_list())

    from rich.table import Table

    table = Table(title="🤖 Available Models", show_header=True)
    table.add_column("Tier / Provider", style="bold")
    table.add_column("Models")

    for tier_info, model_list in all_models.items():
        table.add_row(tier_info, ", ".join(model_list))

    console.print(table)


@app.command()
def config_info(
    config: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to config YAML file"
    ),
) -> None:
    """Show current configuration."""
    from cascade.config import load_config

    cfg = load_config(config)

    from rich.table import Table

    table = Table(title="⚙️ Cascade Configuration", show_header=True)
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    table.add_row("T1 Orchestrator", f"{cfg.tiers.t1_orchestrator.provider} / {cfg.tiers.t1_orchestrator.model}")
    table.add_row("T2 Worker", f"{cfg.tiers.t2_worker.provider} / {cfg.tiers.t2_worker.model}")
    table.add_row("T3 Executor", f"{cfg.tiers.t3_executor.provider} / {cfg.tiers.t3_executor.model}")
    table.add_row("Project Root", cfg.project_root)
    table.add_row("Budget Enabled", str(cfg.budget.enabled))
    if cfg.budget.enabled:
        table.add_row("Session Budget", f"${cfg.budget.session_max_cost}" if cfg.budget.session_max_cost else "unlimited")
    table.add_row(
        "Escalation T3→T2",
        f"confidence < {cfg.escalation.t3_confidence_threshold}",
    )
    table.add_row(
        "Escalation T2→T1",
        f"confidence < {cfg.escalation.t2_confidence_threshold}",
    )

    console.print(table)

    # Check API keys
    console.print()
    keys_status = []
    if cfg.api_keys.anthropic:
        keys_status.append("[green]✓ Anthropic[/green]")
    else:
        keys_status.append("[red]✗ Anthropic[/red]")
    if cfg.api_keys.openai:
        keys_status.append("[green]✓ OpenAI[/green]")
    else:
        keys_status.append("[red]✗ OpenAI[/red]")
    if cfg.api_keys.google:
        keys_status.append("[green]✓ Google[/green]")
    else:
        keys_status.append("[red]✗ Google[/red]")

    console.print(f"API Keys: {' | '.join(keys_status)}")


@app.command()
def version() -> None:
    """Show Cascade version."""
    console.print(f"Cascade v{__version__}")


@app.command()
def init(
    path: str = typer.Argument(".", help="Directory to initialize"),
) -> None:
    """Initialize a cascade.yaml config file in the given directory."""
    import shutil

    target = Path(path) / "cascade.yaml"
    if target.exists():
        console.print(f"[yellow]Config already exists: {target}[/yellow]")
        raise typer.Exit(1)

    # Find the example config
    example = Path(__file__).parent.parent / "config.example.yaml"
    if not example.exists():
        # Fallback: generate a minimal config
        target.write_text(
            "# Cascade Configuration\n"
            "# See https://github.com/varunsv/cascade-ai for full options\n\n"
            "tiers:\n"
            "  t1_orchestrator:\n"
            "    provider: anthropic\n"
            "    model: claude-sonnet-4-20250514\n"
            "  t2_worker:\n"
            "    provider: anthropic\n"
            "    model: claude-sonnet-4-20250514\n"
            "  t3_executor:\n"
            "    provider: ollama\n"
            "    model: qwen2.5-coder:7b\n"
        )
    else:
        shutil.copy(example, target)

    console.print(f"[green]✓ Created {target}[/green]")
    console.print("Edit it with your API keys and model preferences.")


if __name__ == "__main__":
    app()
