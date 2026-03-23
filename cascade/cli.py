"""Cascade CLI — command-line interface."""

from __future__ import annotations

import asyncio
import warnings

# Suppress unclosed transport warnings from asyncio/httpx
warnings.filterwarnings("ignore", category=ResourceWarning)
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from cascade import __version__

app = typer.Typer(
    name="cascade",
    help="🌊 Cascade — Dynamic Fractal AI Agent System",
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
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Execute a task using the Cascade fractal agent system."""
    from cascade.api import Cascade
    from cascade.config import load_config
    from cascade.utils.display import (
        print_banner,
        print_cost_summary,
        print_escalation,
        print_result,
        print_task_start,
        print_agent_header,
        print_thinking,
        print_tool_call,
        print_tool_result,
        print_auditor_block,
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
    async def on_agent_spawn(model_id, desc):
        print_agent_header(model_id, desc)

    async def on_tool_call_cb(name, args):
        print_tool_call(name, args)

    async def on_thinking_cb(text):
        print_thinking(text)

    async def on_escalation_cb(from_t, to_t, reason):
        print_escalation(from_t, to_t, reason)

    async def on_auditor_block_cb(tool_name, reason):
        print_auditor_block(tool_name, reason)

    async def on_tool_result_cb(name, success, output):
        print_tool_result(success, output)

    agent.on_tier_start = on_agent_spawn
    agent.on_tool_call = on_tool_call_cb
    agent.on_tool_result = on_tool_result_cb
    agent.on_thinking = on_thinking_cb
    agent.on_escalation = on_escalation_cb
    agent.on_auditor_block = on_auditor_block_cb

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
    """List available models in the pool."""
    from cascade.api import Cascade
    from cascade.config import load_config

    cfg = load_config(config)
    agent = Cascade(config=cfg)

    async def _list():
        return await agent.list_models()

    all_models = asyncio.run(_list())

    from rich.table import Table

    table = Table(title="🤖 Available Models", show_header=True)
    table.add_column("Model Pool / Provider", style="bold")
    table.add_column("Available Models Endpoint")

    for model_info, model_list in all_models.items():
        table.add_row(model_info, ", ".join(model_list))

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

    table.add_row("Default Planner", cfg.default_planner)
    
    for m in cfg.models:
        table.add_row(f"Model: {m.id}", f"{m.provider} / {m.model}")
        
    table.add_row("Project Root", cfg.project_root)
    table.add_row("Budget Enabled", str(cfg.budget.enabled))
    if cfg.budget.enabled:
        table.add_row("Session Budget", f"${cfg.budget.session_max_cost}" if cfg.budget.session_max_cost else "unlimited")
    
    table.add_row(
        "Escalation Confidence",
        f"< {cfg.escalation.confidence_threshold}",
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
    global_config: bool = typer.Option(False, "--global", "-g", help="Initialize global config in ~/.cascade/config.yaml"),
) -> None:
    """Initialize a cascade.yaml config file."""
    import shutil
    import os

    if global_config:
        cascade_dir = Path.home() / ".cascade"
        cascade_dir.mkdir(parents=True, exist_ok=True)
        target = cascade_dir / "config.yaml"
    else:
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
            "default_planner: planner\n"
            "models:\n"
            "  - id: planner\n"
            "    provider: anthropic\n"
            "    model: claude-sonnet-4-20250514\n"
            "  - id: worker\n"
            "    provider: anthropic\n"
            "    model: claude-sonnet-4-20250514\n"
            "  - id: local\n"
            "    provider: ollama\n"
            "    model: qwen2.5-coder:7b\n"
        )
    else:
        shutil.copy(example, target)

    console.print(f"[green]✓ Created {target}[/green]")
    console.print("Edit it with your API keys and model preferences.")

@app.command()
def chat(
    config: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to config YAML file"
    ),
    project_root: Optional[str] = typer.Option(
        None, "--root", "-r", help="Project root directory"
    ),
    budget: Optional[float] = typer.Option(
        None, "--budget", "-b", help="Max session cost in dollars"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Start an interactive chat session with Cascade."""
    from cascade.api import Cascade
    from cascade.config import load_config
    from rich.prompt import Prompt
    from cascade.utils.display import (
        print_banner,
        print_cost_summary,
        print_escalation,
        print_result,
        print_agent_header,
        print_thinking,
        print_tool_call,
        print_tool_result,
        print_auditor_block,
    )

    print_banner()
    console.print("[bold green]Starting interactive chat mode. Type 'exit' or 'quit' to end.[/bold green]\n")

    cfg = load_config(config)
    if verbose:
        cfg.verbose = True
    if budget is not None:
        cfg.budget.enabled = True
        cfg.budget.session_max_cost = budget

    agent = Cascade(
        config=cfg,
        project_root=project_root or ".",
    )

    # Wire up display callbacks
    async def on_agent_spawn(model_id, desc):
        print_agent_header(model_id, desc)

    async def on_tool_call_cb(name, args):
        print_tool_call(name, args)

    async def on_thinking_cb(text):
        print_thinking(text)

    async def on_escalation_cb(from_t, to_t, reason):
        print_escalation(from_t, to_t, reason)

    async def on_auditor_block_cb(tool_name, reason):
        print_auditor_block(tool_name, reason)

    async def on_tool_result_cb(name, success, output):
        print_tool_result(success, output)

    agent.on_tier_start = on_agent_spawn
    agent.on_tool_call = on_tool_call_cb
    agent.on_tool_result = on_tool_result_cb
    agent.on_thinking = on_thinking_cb
    agent.on_escalation = on_escalation_cb
    agent.on_auditor_block = on_auditor_block_cb

    chat_history = ""
    while True:
        try:
            task = Prompt.ask("[bold blue]You[/bold blue]")
            if task.lower() in ("exit", "quit"):
                break
            if not task.strip():
                continue

            full_task = f"Context from previous turns:\n{chat_history}\n\nCurrent Request:\n{task}" if chat_history else task
            result = asyncio.run(agent.run_async(full_task))
            
            console.print()
            print_result(result.success, result.summary)
            print_cost_summary(agent.cost_tracker.get_summary())
            
            # Simple summarization for context memory
            short_res = result.summary[:500] + "..." if len(result.summary) > 500 else result.summary
            chat_history += f"User: {task}\nCascade: {short_res}\n\n"
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping current task.[/yellow]")
            continue
        except EOFError:
            break
        except Exception as e:
             console.print(f"\n[bold red]Error:[/bold red] {e}")


if __name__ == "__main__":
    app()
