"""Diff preview tooling for staged or pending changes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cascade.tools.base import BaseTool, ToolCapability, ToolResult, ToolScope


class DiffPreviewTool(BaseTool):
    """Preview a diff and optionally stage it under pending_changes/."""

    name = "diff_preview"
    description = (
        "Preview a unified diff patch and optionally write it to pending_changes/ for later application."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "patch": {"type": "string", "description": "Unified diff content to preview."},
            "stage_name": {
                "type": "string",
                "description": "Optional file name for storing the patch under pending_changes/.",
            },
        },
        "required": ["patch"],
    }
    capabilities = (ToolCapability.READ,)
    scope = ToolScope.FILE

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()

    async def execute(self, **kwargs: Any) -> ToolResult:
        patch = kwargs.get("patch", "")
        stage_name = kwargs.get("stage_name")
        if not patch:
            return ToolResult(success=False, error="No patch content provided")

        output = patch
        if stage_name:
            pending_dir = self.project_root / "pending_changes"
            pending_dir.mkdir(parents=True, exist_ok=True)
            stage_path = pending_dir / stage_name
            stage_path.write_text(patch, encoding="utf-8")
            output += f"\n\nStaged preview at {stage_path.relative_to(self.project_root)}"
        return ToolResult(output=output)
