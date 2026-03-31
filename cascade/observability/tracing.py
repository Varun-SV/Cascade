"""Trace writing and rendering for Cascade task executions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.tree import Tree

from cascade.core.runtime import ExecutionEvent


class TaskTraceWriter:
    """Persist execution events as JSONL and a materialized trace file."""

    def __init__(self, trace_root: str, task_id: str):
        self.task_id = task_id
        self.trace_dir = Path(trace_root) / task_id
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.trace_dir / "events.jsonl"
        self.trace_path = self.trace_dir / "trace.json"
        self._events: list[dict[str, Any]] = []

    async def __call__(self, event: ExecutionEvent) -> None:
        payload = event.model_dump()
        self._events.append(payload)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def finalize(self) -> dict[str, Any]:
        """Write the materialized trace summary."""
        trace = {
            "task_id": self.task_id,
            "event_count": len(self._events),
            "events": self._events,
        }
        self.trace_path.write_text(json.dumps(trace, indent=2), encoding="utf-8")
        return trace


def load_trace(task_id: str, trace_root: str) -> dict[str, Any]:
    """Load a materialized trace file."""
    trace_path = Path(trace_root) / task_id / "trace.json"
    return json.loads(trace_path.read_text(encoding="utf-8"))


def render_trace_tree(trace: dict[str, Any]) -> str:
    """Render a task trace as a rich tree and return the text output."""
    tree = Tree(f"Task {trace.get('task_id', 'unknown')}")
    nodes: dict[str, Any] = {"": tree}

    for event in trace.get("events", []):
        agent_id = event.get("agent_id", "")
        parent_agent_id = event.get("parent_agent_id", "")
        label = event.get("message") or event.get("event_type", "event")
        detail = event.get("event_type", "")
        node_parent = nodes.get(parent_agent_id or "", tree)
        if agent_id and agent_id not in nodes:
            nodes[agent_id] = node_parent.add(f"{agent_id} [{event.get('model_id', '')}]")
        current_parent = nodes.get(agent_id, node_parent)
        current_parent.add(f"{detail}: {label}")

    console = Console(record=True, width=120)
    console.print(tree)
    return console.export_text()
