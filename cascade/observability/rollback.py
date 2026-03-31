"""Rollback artifact capture and restoration for task-scoped file changes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cascade.core.runtime import ExecutionContext

if TYPE_CHECKING:
    from cascade.tools.base import ToolResult


def _affected_paths(tool_name: str, kwargs: dict[str, Any]) -> list[str]:
    if tool_name in {"write_file", "edit_file", "search_replace", "delete_path"}:
        path = kwargs.get("path")
        return [path] if path else []
    if tool_name == "move_path":
        return [candidate for candidate in [kwargs.get("source"), kwargs.get("destination")] if candidate]
    if tool_name == "apply_patch":
        return []
    return []


class RollbackManager:
    """Capture before/after snapshots for task rollback."""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()

    def _rollback_dir(self, execution_context: ExecutionContext) -> Path:
        path = Path(execution_context.task_artifact_dir) / "rollback"
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def capture_before(
        self,
        *,
        tool_name: str,
        kwargs: dict[str, Any],
        execution_context: ExecutionContext,
    ) -> None:
        rollback_dir = self._rollback_dir(execution_context)
        for path_str in _affected_paths(tool_name, kwargs):
            if not path_str:
                continue
            path = (self.project_root / path_str).resolve()
            if not str(path).startswith(str(self.project_root)):
                continue
            snapshot = {
                "path": path_str,
                "exists": path.exists(),
                "content": path.read_text(encoding="utf-8", errors="replace") if path.exists() and path.is_file() else None,
            }
            snapshot_path = rollback_dir / f"{path_str.replace('/', '__')}.before.json"
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    async def capture_after(
        self,
        *,
        tool_name: str,
        kwargs: dict[str, Any],
        execution_context: ExecutionContext,
        result: "ToolResult",
    ) -> None:
        rollback_dir = self._rollback_dir(execution_context)
        manifest = {"tool_name": tool_name, "success": result.success, "kwargs": kwargs}
        (rollback_dir / "manifest.jsonl").open("a", encoding="utf-8").write(
            json.dumps(manifest, default=str) + "\n"
        )

    def restore(self, task_artifact_dir: str) -> list[str]:
        """Restore file snapshots recorded for a task."""
        rollback_dir = Path(task_artifact_dir) / "rollback"
        restored: list[str] = []
        for snapshot_file in rollback_dir.glob("*.before.json"):
            snapshot = json.loads(snapshot_file.read_text(encoding="utf-8"))
            path = (self.project_root / snapshot["path"]).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            if snapshot["exists"]:
                path.write_text(snapshot["content"] or "", encoding="utf-8")
            elif path.exists():
                if path.is_file():
                    path.unlink()
            restored.append(snapshot["path"])
        return sorted(restored)
