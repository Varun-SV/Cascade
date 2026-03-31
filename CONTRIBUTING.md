# Contributing

Cascade is designed to be hackable by experienced engineers without requiring a week-long codebase tour. This guide focuses on the shortest path from clone to meaningful contribution.

## Architecture at a Glance

- `cascade/api.py`: composition root for config, providers, tools, plugins, strategy selection, and public APIs.
- `cascade/core/`: agent runtime, approvals, escalation, task models, execution events, and working memory.
- `cascade/providers/`: concrete provider adapters, the provider router, and benchmarking helpers.
- `cascade/tools/`: file, git, shell, semantic search, diff preview, and tool registry runtime.
- `cascade/observability/`: traces, journaling, and rollback artifacts.
- `cascade/strategy/`: swappable planning and execution strategies.
- `cascade/plugins/`: extension discovery and plugin metadata persistence.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Optional extras:

```bash
pip install -e .[semantic]
pip install -e .[otel]
pip install -e .[dashboard]
pip install -e .[docs]
```

## Running the Checks

```bash
ruff check .
mypy --strict cascade
pytest
pytest tests/harness -q
```

## Adding a Tool

1. Create a tool class in `cascade/tools/` that subclasses `BaseTool`.
2. Fill out the manifest-driving class attributes: `name`, `description`, `capabilities`, `scope`, `mutating`, `reversible`, and `cache_ttl_seconds`.
3. Implement `execute()` and, for mutating tools, a useful `dry_run()`.
4. Register the tool in `_create_tool_registry()` inside `cascade/api.py`.
5. Add at least one unit test and update `docs/Tool-Reference.md` if the tool is user-facing.

## Adding a Provider

1. Implement the `BaseProvider` interface in `cascade/providers/`.
2. Support both `generate()` and `stream()` so the runtime can treat providers uniformly.
3. Register the provider factory in `_create_raw_provider()` or expose it through the `cascade.providers` entry-point group.
4. Add unit tests that cover normal execution plus any provider-specific error mapping.

## Adding a Strategy

1. Implement `PlannerStrategy` in `cascade/strategy/`.
2. Wire it in through a plugin entry point or add it to `_strategies` in `Cascade`.
3. Make sure the strategy still returns the existing `TaskResult` schema from `Cascade.run()` and `Cascade.run_async()`.

## Design Rules for Contributions

- Keep the Python API backward compatible unless a breaking change has been explicitly approved.
- Prefer additive configuration. New keys should be optional with safe defaults.
- Use type annotations throughout. New modules should pass `mypy --strict`.
- Avoid coupling provider-specific behavior into the core runtime.
- Favor real safety and observability over “best effort” logging that cannot be trusted later.
