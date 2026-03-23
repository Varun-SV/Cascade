# 🌊 Cascade

**Multi-Tier AI Agent Orchestration System**

Cascade is a CLI tool and Python library that hierarchically delegates coding tasks across three model tiers to minimize cost while maximizing capability.

```
User ──► T1 Orchestrator (Claude Opus / GPT-5)
              │
              ├──► T2 Worker (Claude Sonnet / GPT-4o-mini)
              │         │
              │         └──► T3 Executor (Local SLM via Ollama)
              │
              └──► Escalation handling
```

## Features

- **3-Tier Architecture**: Large model plans → Medium model executes → Local SLM handles fast actions
- **4 Providers**: Anthropic, OpenAI, Google Gemini, Ollama (local)
- **13 Tools**: File ops, shell, code search, git, web
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
tiers:
  t1_orchestrator:
    provider: anthropic
    model: claude-sonnet-4-20250514
  t2_worker:
    provider: anthropic
    model: claude-sonnet-4-20250514
  t3_executor:
    provider: ollama
    model: qwen2.5-coder:7b

api_keys:
  anthropic: "sk-ant-..."
  openai: "sk-..."
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
```

## License

Dual licensed:
- **Personal/Non-commercial**: Free
- **Commercial**: Requires a paid license

See [LICENSE](LICENSE) for details.
