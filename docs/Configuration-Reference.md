# Configuration Reference

## Core Keys

- `default_planner`: root model ID used for orchestration
- `default_auditor`: optional model ID used by the Sentinel auditor
- `models[]`: provider/model definitions available to the runtime

## Runtime

```yaml
runtime:
  max_reflections: 3
  stream_events: true
  preflight_confirmation: true
  retry_reflection_enabled: true
```

## Approvals

```yaml
approvals:
  mode: guarded   # auto | guarded | strict
  allowed_command_prefixes:
    - ["pytest"]
```

`power_user` is still accepted and normalized to `auto` for backward compatibility.

## Budget

```yaml
budget:
  enabled: true
  session_max_cost: 2.0
  task_max_cost: 0.5
  ledger_path: "~/.cascade/state.db"
  tier_max_costs:
    planner: 1.0
```

## Observability

```yaml
observability:
  trace_dir: ".cascade/traces"
  journal_path: ".cascade/journal.log"
  otel_enabled: false
```

## Plugins

```yaml
plugins:
  registry_path: "~/.cascade/plugins.json"
  enabled_packages: []
  auto_load: true
  strategy: default
```
