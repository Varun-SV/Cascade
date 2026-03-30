# 🌊 Cascade

**Multi-Tier AI Agent Orchestration System**

Cascade is a CLI tool and Python library for building a coding agent that does not rely on a single model for everything.

The project is trying to achieve three things at once:
- use strong models for planning and hard reasoning
- use cheaper or local models for narrower subtasks
- keep tool use safer and more controllable than a raw "run anything" agent

```
User ──► T1 Orchestrator (Claude Opus / GPT-5)
              │
              ├──► T2 Worker (Claude Sonnet / GPT-4o-mini)
              │         │
              │         └──► T3 Executor (Local SLM via Ollama)
              │
              └──► Escalation handling
```

## What Cascade Is

Cascade is an agent runtime for software tasks. You give it a request like "fix this bug", "add tests", or "inspect this repo", and it decides how to break that work down across a small pool of models.

Instead of assuming one model should plan, read files, edit code, run commands, and recover from failure all by itself, Cascade treats those as separate concerns. The root planner can inspect the repository, delegate focused work to child agents, and escalate or retry when something goes wrong.

## What It Is Trying To Achieve

At a high level, Cascade is aiming to be a practical coding assistant that is:

- **Cheaper**: push simple reads and narrow subtasks to smaller or local models
- **More capable**: let stronger models coordinate bigger tasks and recover from failure
- **Safer**: guard risky shell, process, file, and git actions behind approvals
- **More modular**: keep providers, tools, agent logic, and CLI behavior separated so the system can grow over time

## How It Works

When you run a task, Cascade follows a top-level loop like this:

1. **Receive the task**
   The root planner model gets your request through the CLI or Python API.
2. **Inspect the repo**
   The planner can use a small read-only discovery toolset to understand the project before doing anything expensive or risky.
3. **Delegate focused work**
   If the task is bigger than a single step, the planner spawns child agents and gives them only the tools they need.
4. **Execute with tools**
   Child agents can read files, search code, apply patches, run commands, manage interactive processes, inspect git state, and fetch web content.
5. **Gate risky actions**
   Destructive or mutating actions can require approval depending on the configured approval mode.
6. **Escalate when needed**
   If an agent loses confidence or repeatedly fails, the task bubbles back up instead of silently drifting.
7. **Return one final result**
   The system reports the outcome, along with cost tracking across the models used.

## Top-Level Architecture

These are the main pieces of the project:

- `cascade/api.py`
  The main public entry point. It builds providers, registers tools, creates the root agent, and runs tasks.
- `cascade/core/agent.py`
  The recursive agent runtime. This is where tool calls, delegation, approvals, and escalation come together.
- `cascade/tools/`
  The tool layer. This includes file operations, code search, shell/process control, git operations, and web access.
- `cascade/providers/`
  Provider adapters for Anthropic, OpenAI, Google Gemini, and Ollama.
- `cascade/cli.py`
  The command-line interface for one-shot runs, interactive chat, config bootstrap, and model inspection.
- `cascade/config.py`
  Configuration loading for models, budgets, approvals, API keys, and project root sandboxing.

## Features

- **3-Tier Architecture**: Large model plans → Medium model executes → Local SLM handles fast actions
- **4 Providers**: Anthropic, OpenAI, Google Gemini, Ollama (local)
- **Expanded Coding Toolchain**: Multi-file reads, patch editing, guarded shell/process control, richer git ops, and code search
- **Confidence-Based Escalation**: Automatic escalation when agents hit limits
- **Cost Tracking**: Optional per-tier and session budget limits
- **Dual Interface**: CLI tool + Python library API

## Quick Start

```bash
# Install
pip install -e .

# Initialize config
cascade init

# Edit cascade.yaml with your API keys, then:
cascade run "list all Python files and count lines of code"
```

## Example Task Flow

If you ask Cascade to "add error handling to auth.py", the system will usually behave like this:

1. The planner inspects the repo with read-only tools.
2. It decides whether to solve the change itself or delegate to a worker.
3. The worker reads the relevant files, edits the code with targeted tools such as `search_replace` or `apply_patch`, and verifies the result.
4. If tests or commands are needed, it can run them through the guarded shell tools.
5. The result is summarized and returned to you in one response.

## Python API

```python
from cascade import Cascade

agent = Cascade(config_path="./cascade.yaml")
result = agent.run("add error handling to auth.py")

print(result.summary)
print(f"Cost: ${result.total_cost:.4f}")
```

## Configuration

Copy `config.example.yaml` to `cascade.yaml` and edit:

```yaml
default_planner: planner
default_auditor: local

models:
  - id: planner
    provider: anthropic
    model: claude-sonnet-4-20250514
  - id: worker
    provider: anthropic
    model: claude-sonnet-4-20250514
  - id: local
    provider: ollama
    model: qwen2.5-coder:7b

api_keys:
  anthropic: "sk-ant-..."
  openai: "sk-..."
  google: ""

approvals:
  mode: guarded
```

API keys can also be set via environment variables:
- `CASCADE_ANTHROPIC_API_KEY`
- `CASCADE_OPENAI_API_KEY`
- `CASCADE_GOOGLE_API_KEY`

## CLI Commands

| Command | Description |
|---------|-------------|
| `cascade run "task"` | Execute a task |
| `cascade models` | List available models |
| `cascade config-info` | Show current configuration |
| `cascade init` | Create a cascade.yaml config file |
| `cascade version` | Show version |

### Options

```bash
cascade run "task" --budget 0.50      # Set $0.50 session budget
cascade run "task" --verbose          # Verbose output
cascade run "task" --root ./myproject # Set project root
cascade chat                          # Start interactive mode
cascade run "task" --approval-mode strict
```

## License

Dual licensed:
- **Personal/Non-commercial**: Free
- **Commercial**: Requires a paid license

See [LICENSE](LICENSE) for details.
