# Running in CI

For CI workloads, set approval mode to `auto` and prefer deterministic prompts.

## Recommended Command

```bash
cascade run "apply the requested patch set" --approval-mode auto --output json
```

## CI Workflow

The default GitHub Actions workflow runs:

- `ruff check .`
- `mypy --strict cascade`
- `pytest`
- `pytest tests/harness -q`

An additional Ollama job installs Ollama, pulls a lightweight coding model, and runs the harness suite to preserve the local-only path.
