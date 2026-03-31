# Getting Started

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

For development:

```bash
pip install -e .[dev]
```

## Configure

```bash
cascade init
```

Edit `cascade.yaml` and set the providers you want to use. For a fully local setup, keep an Ollama model configured and running.

## First Commands

```bash
cascade doctor
cascade explain "add tests for parser.py"
cascade run "fix the failing parser tests"
```

## Key Concepts

- `run`: execute a task
- `explain`: preview the plan without executing
- `trace`: inspect what the agents actually did
- `budget`: inspect cost history
- `rollback`: restore file snapshots from a task
