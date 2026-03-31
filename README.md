# 🌊 Cascade

**Reliable multi-model software engineering agents for the CLI and Python.**

Cascade is an open-source agent runtime for real coding work. Instead of asking one model to plan, inspect a repo, edit files, run commands, recover from failures, and stay safe all at once, Cascade splits those responsibilities across a small pool of models and a guarded tool layer.

It is built for people who want:

- stronger planning than a single-agent loop
- cheaper execution through smaller or local models
- meaningful approvals for risky actions
- traces, journaling, rollback, and cost visibility
- a runtime they can extend with their own tools, providers, and strategies

```text
User / CLI / Python API
          │
          ▼
   Root Planner Agent
          │
          ├──► discovery tools
          ├──► child worker agents
          ├──► provider fallback / context management
          └──► reflection, retry, or escalation
```

## What Cascade Does

You give Cascade a software task like:

- "fix the failing tests"
- "add error handling to auth.py"
- "inspect this repo and explain the architecture"
- "refactor the CLI and update docs"

Cascade then:

1. inspects the repository with read-only discovery tools
2. builds a plan and, when appropriate, asks for confirmation before executing
3. delegates focused subtasks to child agents with explicit tool and budget boundaries
4. executes code and repo operations through a guarded tool registry
5. records traces, journal entries, rollback artifacts, and budget attribution
6. retries with reflection when something fails instead of blindly repeating the same move

## Why It Exists

Most coding agents fail in one of two ways:

- they are powerful but expensive, opaque, and hard to trust
- they are cheap and fast but brittle once real repo work starts

Cascade is trying to be the practical middle ground:

- **More capable**: stronger models coordinate, smaller models execute narrow subtasks
- **More efficient**: local or cheaper models can handle discovery, summarization, and routine work
- **More trustworthy**: approvals, dry-run previews, traces, journaling, and rollback are built into the runtime
- **More extensible**: providers, tools, and planning strategies are pluggable

## How The Runtime Works

At a high level, a task flows through Cascade like this:

1. **Composition root**
   `Cascade` wires together config, tools, providers, strategy selection, budgets, and observability.
2. **Preflight planning**
   The active strategy can inspect the repo and produce a plan preview with estimated cost and risks.
3. **Recursive execution**
   The root `CascadeAgent` keeps working memory, calls tools, delegates subtasks, and escalates when confidence drops.
4. **Provider routing**
   Requests go through a provider router that can apply fallback behavior and prompt-budget management.
5. **Guarded tools**
   File, git, shell, process, diff preview, and semantic search tools run through a registry that handles approvals, dry runs, caching, and rollback hooks.
6. **Observability**
   Execution events are emitted once and consumed by traces, journals, and budget tracking.

## Key Capabilities

- **Recursive agent runtime**
  Working memory, structured delegation envelopes, and reflection-retry-escalate behavior.
- **Unified provider routing**
  Anthropic, OpenAI, Google Gemini, Ollama, plus fallback-aware execution and context-window handling.
- **Production-grade coding tools**
  Multi-file reads, search/replace, patch application, diff preview staging, semantic code search, shell/process control, and richer git operations.
- **Safety and trust**
  `auto`, `guarded`, and `strict` approval modes, dry-run previews, action journaling, and rollback support.
- **Observability**
  Task traces under `.cascade/traces/`, audit journaling, and budget attribution by task, model, provider, and tier.
- **Extensibility**
  Plugin-ready tools, providers, and orchestration strategies.

## Quick Start

### Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

For development:

```bash
pip install -e .[dev]
```

### Initialize config

```bash
cascade init
```

Then edit `cascade.yaml` and choose your providers.

### First commands

```bash
cascade doctor
cascade explain "add tests for auth.py"
cascade run "fix the failing tests"
```

## Two Good Setup Paths

### Hosted-model setup

Use Anthropic, OpenAI, or Google for planning/worker tiers and optionally keep Ollama around for local summarization and fallback.

Environment variables:

- `CASCADE_ANTHROPIC_API_KEY`
- `CASCADE_OPENAI_API_KEY`
- `CASCADE_GOOGLE_API_KEY`

### Local-first setup

If you want a local-only workflow, keep an Ollama model configured and running:

```bash
ollama serve
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
```

That gives you a fully local coding model plus local embeddings for semantic code search.

## Example Task Flow

If you ask Cascade to "add error handling to `auth.py`", a typical run looks like this:

1. the planner inspects the repo with discovery tools like `find_files`, `glob_files`, `grep_search`, and `read_files`
2. Cascade shows a plan preview in interactive mode unless you skip it
3. the root agent either performs the edit directly or delegates a focused subtask to a worker
4. the worker uses tools like `search_replace`, `apply_patch`, `diff_preview`, and `run_command`
5. risky actions are routed through the approval layer
6. the final result includes a summary, while traces and cost data are recorded in the background

## Python API

```python
import asyncio

from cascade import Cascade

agent = Cascade(config_path="./cascade.yaml")

result = agent.run("add error handling to auth.py")
print(result.summary)
print(f"Cost: ${result.total_cost:.4f}")

preview = asyncio.run(agent.explain("write tests for auth.py"))
print(preview.summary)

trace = agent.trace("task-id")
print(trace["task_id"])
```

## CLI Commands

| Command | What it does |
|---|---|
| `cascade run "task"` | Execute a task |
| `cascade explain "task"` | Preview the execution plan without running it |
| `cascade doctor` | Validate config and environment setup |
| `cascade budget` | Show current session and historical cost summaries |
| `cascade trace <task-id>` | Render a recorded execution trace |
| `cascade rollback <task-id>` | Restore task snapshots |
| `cascade benchmark` | Run the built-in benchmark suite |
| `cascade plugin ...` | Manage plugins |
| `cascade chat` | Start interactive mode |
| `cascade models` | List available provider models |
| `cascade config-info` | Show the active configuration |
| `cascade init` | Create a starter config file |
| `cascade version` | Show version |

Useful examples:

```bash
cascade run "fix the parser tests" --budget 0.50
cascade run "refactor the CLI" --approval-mode strict
cascade run "inspect this repo" --output json
cascade explain "add semantic search to the tool layer"
cascade trace a1b2c3d4
cascade plugin list
```

## Configuration

Start from [`config.example.yaml`](config.example.yaml). A shortened example:

```yaml
default_planner: planner
default_auditor: local

models:
  - id: planner
    provider: anthropic
    model: claude-sonnet-4-20250514
    fallback_models: [worker, local]

  - id: worker
    provider: openai
    model: gpt-4o-mini

  - id: local
    provider: ollama
    model: qwen2.5-coder:7b

approvals:
  mode: guarded

runtime:
  max_reflections: 3
  preflight_confirmation: true

semantic_search:
  enabled: true
  ollama_embedding_model: "nomic-embed-text"
```

Important config areas:

- `models`
  Available models in the pool, including fallback models and context windows.
- `approvals`
  `auto`, `guarded`, or `strict`.
- `budget`
  Session, task, model, and tier limits plus the SQLite ledger path.
- `runtime`
  Reflection and preflight behavior.
- `observability`
  Trace directory, journal path, and future telemetry hooks.
- `plugins`
  Plugin registry path, enabled packages, and strategy selection.
- `semantic_search`
  Local embedding model and base URL.

## Project Structure

- [`cascade/api.py`](cascade/api.py)
  Public composition root and Python API.
- [`cascade/core/agent.py`](cascade/core/agent.py)
  Recursive agent runtime with working memory and structured delegation.
- [`cascade/tools/`](cascade/tools)
  File, git, shell, process, diff preview, semantic search, and web tooling.
- [`cascade/providers/`](cascade/providers)
  Provider adapters, routing, and benchmarking.
- [`cascade/observability/`](cascade/observability)
  Traces, journaling, and rollback.
- [`cascade/strategy/`](cascade/strategy)
  Swappable planning and execution strategies.
- [`cascade/plugins/`](cascade/plugins)
  Plugin protocols and registry persistence.

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [docs/Getting-Started.md](docs/Getting-Started.md)
- [docs/Configuration-Reference.md](docs/Configuration-Reference.md)
- [docs/Tool-Reference.md](docs/Tool-Reference.md)
- [docs/Building-Custom-Tools.md](docs/Building-Custom-Tools.md)
- [docs/Cost-Management.md](docs/Cost-Management.md)
- [docs/Running-in-CI.md](docs/Running-in-CI.md)

## License

Dual licensed:

- **Personal / non-commercial**: free
- **Commercial**: requires a paid license

See [LICENSE](LICENSE) for details.
