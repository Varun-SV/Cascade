"""Cascade CLI with execution, planning, tracing, budget, and plugin workflows."""

from __future__ import annotations

import asyncio
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from cascade import __version__
from cascade.core.approval import ApprovalDecision, ApprovalMode, ApprovalRequest
from cascade.observability.tracing import render_trace_tree

warnings.filterwarnings("ignore", category=ResourceWarning)

app = typer.Typer(
    name="cascade",
    help=(
        "Cascade: reliable multi-model software engineering agents.\n\n"
        "Examples:\n"
        "  cascade run \"add tests for auth.py\"\n"
        "  cascade explain \"refactor the budget tracker\"\n"
        "  cascade trace <task-id>\n"
    ),
    add_completion=False,
    pretty_exceptions_show_locals=False,
)
plugin_app = typer.Typer(
    name="plugin",
    help=(
        "Manage Cascade extensions.\n\n"
        "Examples:\n"
        "  cascade plugin list\n"
        "  cascade plugin inspect my-cascade-plugin\n"
        "  cascade plugin install my-cascade-plugin\n"
    ),
)
app.add_typer(plugin_app, name="plugin")
console = Console()


def _build_cli_approval_handler() -> Any:
    """Create a TTY-aware approval prompt for risky tool actions."""

    async def _approve(request: ApprovalRequest) -> ApprovalDecision:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return ApprovalDecision(
                approved=False,
                reason="Approval required, but Cascade is not running in an interactive terminal.",
            )

        console.print()
        console.print(
            f"[bold yellow]Approval required[/bold yellow] for "
            f"[bold]{request.tool_name}[/bold]: {request.reason}"
        )
        if request.summary:
            console.print(f"[dim]{request.summary}[/dim]")
        approved = Confirm.ask("Allow this action?", default=False)
        return ApprovalDecision(approved=approved)

    return _approve


def _emit_json(payload: Any) -> None:
    """Print structured output for scripting and CI."""
    console.print_json(json.dumps(payload, default=str))


def _apply_common_overrides(
    *,
    config_path: Optional[str],
    project_root: Optional[str],
    budget: Optional[float],
    approval_mode: Optional[str],
    verbose: bool,
    no_auditor: bool,
):
    from cascade.config import load_config

    cfg = load_config(config_path)
    if verbose:
        cfg.verbose = True
    if project_root:
        cfg.project_root = project_root
    if budget is not None:
        cfg.budget.enabled = True
        cfg.budget.session_max_cost = budget
    if approval_mode is not None:
        cfg.approvals.mode = ApprovalMode(approval_mode)
    if no_auditor:
        cfg.auditor_enabled = False
    return cfg


def _create_cascade(
    *,
    config_path: Optional[str],
    project_root: Optional[str],
    budget: Optional[float],
    approval_mode: Optional[str],
    verbose: bool,
    no_auditor: bool,
):
    from cascade.api import Cascade

    cfg = _apply_common_overrides(
        config_path=config_path,
        project_root=project_root,
        budget=budget,
        approval_mode=approval_mode,
        verbose=verbose,
        no_auditor=no_auditor,
    )
    return Cascade(
        config=cfg,
        project_root=cfg.project_root,
        approval_callback=_build_cli_approval_handler(),
    )


def _wire_text_callbacks(agent: Any) -> None:
    from cascade.utils.display import (
        print_agent_header,
        print_auditor_block,
        print_escalation,
        print_thinking,
        print_tool_call,
        print_tool_result,
    )

    async def on_agent_spawn(model_id: str, desc: str) -> None:
        print_agent_header(model_id, desc)

    async def on_tool_call_cb(name: str, args: dict[str, Any]) -> None:
        print_tool_call(name, args)

    async def on_thinking_cb(text: str) -> None:
        print_thinking(text)

    async def on_escalation_cb(from_t: str, to_t: str, reason: str) -> None:
        print_escalation(from_t, to_t, reason)

    async def on_auditor_block_cb(tool_name: str, reason: str) -> None:
        print_auditor_block(tool_name, reason)

    async def on_tool_result_cb(name: str, success: bool, output: str) -> None:
        print_tool_result(success, output)

    agent.on_tier_start = on_agent_spawn
    agent.on_tool_call = on_tool_call_cb
    agent.on_tool_result = on_tool_result_cb
    agent.on_thinking = on_thinking_cb
    agent.on_escalation = on_escalation_cb
    agent.on_auditor_block = on_auditor_block_cb


def _render_plan_preview(preview: Any) -> None:
    table = Table(title="Execution Plan", show_header=True)
    table.add_column("Step", style="bold cyan")
    table.add_column("Detail")
    table.add_column("Tools")
    for index, step in enumerate(preview.steps, start=1):
        table.add_row(str(index), step.detail, ", ".join(step.tools))
    console.print(f"[bold]Summary:[/bold] {preview.summary}")
    if preview.estimated_cost is not None:
        console.print(f"[bold]Estimated Cost:[/bold] ${preview.estimated_cost:.4f}")
    if preview.risks:
        console.print("[bold]Risks:[/bold]")
        for risk in preview.risks:
            console.print(f"- {risk}")
    if preview.repo_snapshot:
        console.print("\n[bold]Repo Snapshot:[/bold]")
        console.print(preview.repo_snapshot[:2000])
    console.print()
    console.print(table)


@app.command()
def run(
    task: str = typer.Argument(..., help="Task description to execute."),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to cascade.yaml."),
    project_root: Optional[str] = typer.Option(None, "--root", "-r", help="Project root directory."),
    budget: Optional[float] = typer.Option(None, "--budget", "-b", help="Max session cost in dollars."),
    approval_mode: Optional[str] = typer.Option(
        None,
        "--approval-mode",
        help="Approval mode: auto, guarded, strict, or legacy power_user.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logs."),
    no_auditor: bool = typer.Option(False, "--no-auditor", help="Disable the Sentinel Auditor."),
    yes: bool = typer.Option(False, "--yes", help="Skip the interactive preflight confirmation."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Run a task.

    Examples:
      cascade run "add logging to the API client"
      cascade run "fix failing tests" --budget 0.50 --approval-mode guarded
      cascade run "summarize the repo" --output json
    """
    from cascade.utils.display import print_banner, print_cost_summary, print_result, print_task_start

    agent = _create_cascade(
        config_path=config,
        project_root=project_root,
        budget=budget,
        approval_mode=approval_mode,
        verbose=verbose,
        no_auditor=no_auditor,
    )

    if output != "json":
        print_banner()
        print_task_start(task)
        _wire_text_callbacks(agent)

    try:
        should_preflight = (
            output != "json"
            and agent.config.runtime.preflight_confirmation
            and agent.config.approvals.mode != ApprovalMode.AUTO
            and sys.stdin.isatty()
            and sys.stdout.isatty()
            and not yes
        )
        if should_preflight:
            preview = asyncio.run(agent.explain(task))
            _render_plan_preview(preview)
            if not Confirm.ask("Proceed with execution?", default=True):
                raise typer.Exit(1)

        result = asyncio.run(agent.run_async(task))
        if output == "json":
            _emit_json(
                {
                    "result": result.model_dump(),
                    "budget": agent.budget_summary(),
                }
            )
            return

        console.print()
        print_result(result.success, result.summary)
        print_cost_summary(agent.cost_tracker.get_summary())
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled by user.[/yellow]")
        raise typer.Exit(1)
    except Exception as error:
        console.print(f"\n[bold red]Error:[/bold red] {error}")
        if verbose:
            console.print_exception()
        raise typer.Exit(1)


@app.command()
def explain(
    task: str = typer.Argument(..., help="Task description to plan without executing."),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to cascade.yaml."),
    project_root: Optional[str] = typer.Option(None, "--root", "-r", help="Project root directory."),
    budget: Optional[float] = typer.Option(None, "--budget", "-b", help="Max session cost in dollars."),
    approval_mode: Optional[str] = typer.Option(None, "--approval-mode", help="Approval mode override."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logs."),
    no_auditor: bool = typer.Option(False, "--no-auditor", help="Disable the Sentinel Auditor."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Preview the execution plan.

    Examples:
      cascade explain "refactor the CLI"
      cascade explain "write regression tests for parser.py" --output json
    """
    agent = _create_cascade(
        config_path=config,
        project_root=project_root,
        budget=budget,
        approval_mode=approval_mode,
        verbose=verbose,
        no_auditor=no_auditor,
    )
    preview = asyncio.run(agent.explain(task))
    if output == "json":
        _emit_json(preview.model_dump())
    else:
        _render_plan_preview(preview)


@app.command("doctor")
def doctor(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to cascade.yaml."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Validate the current environment.

    Examples:
      cascade doctor
      cascade doctor --config ./cascade.yaml --output json
    """
    from cascade.config import load_config

    cfg = load_config(config)
    checks: list[dict[str, Any]] = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add_check("config", True, "Configuration loaded successfully.")
    add_check("project_root", Path(cfg.project_root).exists(), f"Project root: {cfg.project_root}")

    required_keys = {
        "anthropic": cfg.api_keys.anthropic,
        "openai": cfg.api_keys.openai,
        "google": cfg.api_keys.google,
    }
    configured_providers = {model.provider for model in cfg.models}
    for provider_name in sorted(configured_providers):
        if provider_name == "ollama":
            add_check("ollama", True, f"Ollama base URL configured: {cfg.ollama.base_url}")
            continue
        add_check(
            f"{provider_name}_api_key",
            bool(required_keys.get(provider_name, "")),
            f"{provider_name} API key {'configured' if required_keys.get(provider_name, '') else 'missing'}",
        )

    if output == "json":
        _emit_json({"checks": checks})
        return

    table = Table(title="Cascade Doctor", show_header=True)
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Detail")
    for check in checks:
        table.add_row(
            check["name"],
            "[green]PASS[/green]" if check["ok"] else "[red]FAIL[/red]",
            check["detail"],
        )
    console.print(table)
    if any(not check["ok"] for check in checks):
        raise typer.Exit(1)


@app.command("budget")
def budget_cmd(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to cascade.yaml."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Show budget and historical cost summaries.

    Examples:
      cascade budget
      cascade budget --output json
    """
    agent = _create_cascade(
        config_path=config,
        project_root=None,
        budget=None,
        approval_mode=None,
        verbose=False,
        no_auditor=False,
    )
    summary = agent.budget_summary()
    if output == "json":
        _emit_json(summary)
        return

    table = Table(title="Budget Summary", show_header=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Current Session", f"${summary['session_total']:.4f}")
    for provider_name, total in summary.get("provider_totals", {}).items():
        table.add_row(f"Provider: {provider_name}", f"${total:.4f}")
    console.print(table)
    if summary.get("top_tasks"):
        console.print("\n[bold]Most Expensive Tasks[/bold]")
        for item in summary["top_tasks"]:
            console.print(f"- {item['task_id']}: ${item['total_cost']:.4f} | {item['description']}")


@app.command("trace")
def trace_cmd(
    task_id: str = typer.Argument(..., help="Task ID to render."),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to cascade.yaml."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Render a recorded execution trace.

    Examples:
      cascade trace a1b2c3d4
      cascade trace a1b2c3d4 --output json
    """
    agent = _create_cascade(
        config_path=config,
        project_root=None,
        budget=None,
        approval_mode=None,
        verbose=False,
        no_auditor=False,
    )
    trace = agent.trace(task_id)
    if output == "json":
        _emit_json(trace)
        return
    console.print(render_trace_tree(trace))


@app.command("rollback")
def rollback_cmd(
    task_id: str = typer.Argument(..., help="Task ID to roll back."),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to cascade.yaml."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Restore files from the rollback snapshots recorded for a task.

    Examples:
      cascade rollback a1b2c3d4
      cascade rollback a1b2c3d4 --output json
    """
    agent = _create_cascade(
        config_path=config,
        project_root=None,
        budget=None,
        approval_mode=None,
        verbose=False,
        no_auditor=False,
    )
    restored = agent.rollback(task_id)
    if output == "json":
        _emit_json({"task_id": task_id, "restored_paths": restored})
        return
    console.print(f"Restored {len(restored)} path(s).")
    for path in restored:
        console.print(f"- {path}")


@app.command("benchmark")
def benchmark_cmd(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to cascade.yaml."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Run the built-in benchmark suite against configured models.

    Examples:
      cascade benchmark
      cascade benchmark --output json
    """
    agent = _create_cascade(
        config_path=config,
        project_root=None,
        budget=None,
        approval_mode=None,
        verbose=False,
        no_auditor=False,
    )
    results = asyncio.run(agent.benchmark())
    if output == "json":
        _emit_json(results)
        return
    table = Table(title="Model Benchmark Results", show_header=True)
    table.add_column("Model", style="bold")
    table.add_column("Score")
    table.add_column("Average Latency (s)")
    for model_id, result in results.items():
        table.add_row(
            model_id,
            f"{result.get('score', 0.0):.2f}",
            f"{result.get('average_latency_seconds', 0.0):.2f}",
        )
    console.print(table)


@app.command()
def models(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to cascade.yaml."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """List available models.

    Examples:
      cascade models
      cascade models --output json
    """
    agent = _create_cascade(
        config_path=config,
        project_root=None,
        budget=None,
        approval_mode=None,
        verbose=False,
        no_auditor=False,
    )
    all_models = asyncio.run(agent.list_models())
    if output == "json":
        _emit_json(all_models)
        return

    table = Table(title="Available Models", show_header=True)
    table.add_column("Model Pool / Provider", style="bold")
    table.add_column("Available Models")
    for model_info, model_list in all_models.items():
        table.add_row(model_info, ", ".join(model_list))
    console.print(table)


@app.command()
def config_info(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to cascade.yaml."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Show the active configuration.

    Examples:
      cascade config-info
      cascade config-info --output json
    """
    from cascade.config import load_config

    cfg = load_config(config)
    payload = {
        "default_planner": cfg.default_planner,
        "models": [model.model_dump() for model in cfg.models],
        "project_root": cfg.project_root,
        "budget": cfg.budget.model_dump(),
        "approvals": cfg.approvals.model_dump(),
        "runtime": cfg.runtime.model_dump(),
        "observability": cfg.observability.model_dump(),
    }
    if output == "json":
        _emit_json(payload)
        return

    table = Table(title="Cascade Configuration", show_header=True)
    table.add_column("Setting", style="bold")
    table.add_column("Value")
    table.add_row("Default Planner", cfg.default_planner)
    for model in cfg.models:
        table.add_row(f"Model: {model.id}", f"{model.provider} / {model.model}")
    table.add_row("Project Root", cfg.project_root)
    table.add_row("Approval Mode", cfg.approvals.mode.value)
    table.add_row("Trace Dir", cfg.observability.trace_dir)
    table.add_row("Budget Enabled", str(cfg.budget.enabled))
    console.print(table)


@app.command()
def version(
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Show the installed Cascade version.

    Examples:
      cascade version
      cascade version --output json
    """
    if output == "json":
        _emit_json({"version": __version__})
        return
    console.print(f"Cascade v{__version__}")


@app.command()
def init(
    path: str = typer.Argument(".", help="Directory to initialize."),
    global_config: bool = typer.Option(
        False,
        "--global",
        "-g",
        help="Initialize ~/.cascade/config.yaml instead of a local file.",
    ),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Create a starter configuration file.

    Examples:
      cascade init
      cascade init ./myrepo
      cascade init --global
    """
    import shutil

    if global_config:
        cascade_dir = Path.home() / ".cascade"
        cascade_dir.mkdir(parents=True, exist_ok=True)
        target = cascade_dir / "config.yaml"
    else:
        target = Path(path) / "cascade.yaml"

    if target.exists():
        raise typer.BadParameter(f"Config already exists: {target}")

    example = Path(__file__).parent.parent / "config.example.yaml"
    if example.exists():
        shutil.copy(example, target)
    else:
        target.write_text("default_planner: planner\n", encoding="utf-8")

    if output == "json":
        _emit_json({"created": str(target)})
        return
    console.print(f"[green]Created {target}[/green]")


@app.command()
def chat(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to cascade.yaml."),
    project_root: Optional[str] = typer.Option(None, "--root", "-r", help="Project root directory."),
    budget: Optional[float] = typer.Option(None, "--budget", "-b", help="Max session cost in dollars."),
    approval_mode: Optional[str] = typer.Option(None, "--approval-mode", help="Approval mode override."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logs."),
    no_auditor: bool = typer.Option(False, "--no-auditor", help="Disable the Sentinel Auditor."),
) -> None:
    """Start an interactive chat loop.

    Examples:
      cascade chat
      cascade chat --root ./myproject
    """
    from cascade.utils.display import print_banner, print_cost_summary, print_result

    agent = _create_cascade(
        config_path=config,
        project_root=project_root,
        budget=budget,
        approval_mode=approval_mode,
        verbose=verbose,
        no_auditor=no_auditor,
    )
    _wire_text_callbacks(agent)

    print_banner()
    console.print("[bold green]Interactive mode. Type 'exit' or 'quit' to stop.[/bold green]\n")

    while True:
        prompt = Prompt.ask("[bold cyan]You[/bold cyan]")
        if prompt.strip().lower() in {"exit", "quit"}:
            break
        result = asyncio.run(agent.run_async(prompt))
        print_result(result.success, result.summary)
        print_cost_summary(agent.cost_tracker.get_summary())


@plugin_app.command("list")
def plugin_list(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to cascade.yaml."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """List installed plugins."""
    agent = _create_cascade(
        config_path=config,
        project_root=None,
        budget=None,
        approval_mode=None,
        verbose=False,
        no_auditor=False,
    )
    plugins = agent.plugin_registry.list_plugins()
    if output == "json":
        _emit_json({"plugins": plugins})
        return
    if not plugins:
        console.print("No plugins installed.")
        return
    for plugin in plugins:
        console.print(f"- {plugin}")


@plugin_app.command("inspect")
def plugin_inspect(
    package: str = typer.Argument(..., help="Installed plugin package name."),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to cascade.yaml."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Inspect a plugin's entry points."""
    agent = _create_cascade(
        config_path=config,
        project_root=None,
        budget=None,
        approval_mode=None,
        verbose=False,
        no_auditor=False,
    )
    info = agent.plugin_registry.inspect(package)
    if output == "json":
        _emit_json(info)
        return
    console.print_json(json.dumps(info))


@plugin_app.command("install")
def plugin_install(
    package: str = typer.Argument(..., help="PyPI package or install target."),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to cascade.yaml."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Install a plugin package and register it locally."""
    agent = _create_cascade(
        config_path=config,
        project_root=None,
        budget=None,
        approval_mode=None,
        verbose=False,
        no_auditor=False,
    )
    agent.plugin_registry.install(package)
    if output == "json":
        _emit_json({"installed": package})
        return
    console.print(f"Installed plugin: {package}")


@plugin_app.command("remove")
def plugin_remove(
    package: str = typer.Argument(..., help="Installed plugin package name."),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to cascade.yaml."),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    """Remove a plugin package and unregister it locally."""
    agent = _create_cascade(
        config_path=config,
        project_root=None,
        budget=None,
        approval_mode=None,
        verbose=False,
        no_auditor=False,
    )
    agent.plugin_registry.remove(package)
    if output == "json":
        _emit_json({"removed": package})
        return
    console.print(f"Removed plugin: {package}")


if __name__ == "__main__":
    app()
