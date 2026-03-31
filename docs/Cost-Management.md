# Cost Management

Cascade tracks cost in a SQLite-backed budget ledger.

## What Gets Tracked

- session totals
- task totals
- tier totals
- model totals
- provider totals
- subtask attribution

## Commands

```bash
cascade budget
cascade explain "large refactor"
```

`cascade explain` includes an estimated cost derived from historical task classes and built-in priors.

## Budget Controls

```yaml
budget:
  enabled: true
  session_max_cost: 5.0
  task_max_cost: 1.0
  tier_max_costs:
    planner: 2.0
```

When enabled, the runtime raises budget errors once a configured ceiling is crossed.
