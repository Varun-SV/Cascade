"""File operation tools — read, write, edit, list directory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from cascade.tools.base import BaseTool, Tier, ToolResult


class ReadFileTool(BaseTool):
    """Read the contents of a file."""

    name = "read_file"
    description = (
        "Read the contents of a file at the given path. "
        "Returns the file content as text. Supports optional line range."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file to read.",
            },
            "start_line": {
                "type": "integer",
                "description": "Optional start line (1-indexed).",
            },
            "end_line": {
                "type": "integer",
                "description": "Optional end line (1-indexed, inclusive).",
            },
        },
        "required": ["path"],
    }
    allowed_tiers = {Tier.T1, Tier.T2, Tier.T3}

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()

    def _resolve_path(self, path: str) -> Path:
        """Resolve and sandbox a path to the project root."""
        p = Path(path)
        if not p.is_absolute():
            p = self.project_root / p
        p = p.resolve()
        # Sandbox check
        if not str(p).startswith(str(self.project_root)):
            raise PermissionError(f"Access denied: {p} is outside project root")
        return p

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        start_line = kwargs.get("start_line")
        end_line = kwargs.get("end_line")

        try:
            resolved = self._resolve_path(path)
            if not resolved.exists():
                return ToolResult(success=False, error=f"File not found: {path}")
            if not resolved.is_file():
                return ToolResult(success=False, error=f"Not a file: {path}")

            content = resolved.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines(keepends=True)

            if start_line or end_line:
                s = (start_line or 1) - 1
                e = end_line or len(lines)
                lines = lines[s:e]
                content = "".join(lines)

            return ToolResult(output=content)
        except PermissionError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Error reading file: {e}")


class WriteFileTool(BaseTool):
    """Write content to a file, creating it if it doesn't exist."""

    name = "write_file"
    description = (
        "Write content to a file. Creates the file and parent directories if they don't exist. "
        "Overwrites existing content."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to write.",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file.",
            },
        },
        "required": ["path", "content"],
    }
    allowed_tiers = {Tier.T1, Tier.T2}

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()

    def _resolve_path(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.project_root / p
        p = p.resolve()
        if not str(p).startswith(str(self.project_root)):
            raise PermissionError(f"Access denied: {p} is outside project root")
        return p

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        content = kwargs.get("content", "")

        try:
            resolved = self._resolve_path(path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return ToolResult(output=f"Successfully wrote {len(content)} characters to {path}")
        except PermissionError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Error writing file: {e}")


class EditFileTool(BaseTool):
    """Edit a file by replacing a specific text segment."""

    name = "edit_file"
    description = (
        "Edit a file by replacing a target string with new content. "
        "Use this for surgical edits — provide the exact text to find and the replacement."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to edit.",
            },
            "target": {
                "type": "string",
                "description": "The exact text to find and replace.",
            },
            "replacement": {
                "type": "string",
                "description": "The new text to replace the target with.",
            },
        },
        "required": ["path", "target", "replacement"],
    }
    allowed_tiers = {Tier.T1, Tier.T2}

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()

    def _resolve_path(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.project_root / p
        p = p.resolve()
        if not str(p).startswith(str(self.project_root)):
            raise PermissionError(f"Access denied: {p} is outside project root")
        return p

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        target = kwargs.get("target", "")
        replacement = kwargs.get("replacement", "")

        try:
            resolved = self._resolve_path(path)
            if not resolved.exists():
                return ToolResult(success=False, error=f"File not found: {path}")

            content = resolved.read_text(encoding="utf-8")
            if target not in content:
                return ToolResult(
                    success=False,
                    error=f"Target text not found in {path}",
                )

            count = content.count(target)
            new_content = content.replace(target, replacement, 1)
            resolved.write_text(new_content, encoding="utf-8")
            return ToolResult(
                output=f"Replaced 1 of {count} occurrence(s) in {path}"
            )
        except PermissionError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Error editing file: {e}")


class ListDirectoryTool(BaseTool):
    """List contents of a directory."""

    name = "list_directory"
    description = (
        "List files and subdirectories in a directory. "
        "Returns names, types, and sizes."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the directory to list. Defaults to project root.",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum depth to recurse. Default is 1 (immediate children).",
            },
        },
        "required": [],
    }
    allowed_tiers = {Tier.T1, Tier.T2, Tier.T3}

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", ".") or "."
        max_depth = kwargs.get("max_depth", 1)

        try:
            p = Path(path)
            if not p.is_absolute():
                p = self.project_root / p
            p = p.resolve()

            if not p.exists():
                return ToolResult(success=False, error=f"Directory not found: {path}")
            if not p.is_dir():
                return ToolResult(success=False, error=f"Not a directory: {path}")

            entries: list[str] = []
            self._list_recursive(p, p, max_depth, 0, entries)

            if not entries:
                return ToolResult(output="(empty directory)")
            return ToolResult(output="\n".join(entries))
        except Exception as e:
            return ToolResult(success=False, error=f"Error listing directory: {e}")

    def _list_recursive(
        self, root: Path, current: Path, max_depth: int, depth: int, entries: list[str]
    ) -> None:
        if depth >= max_depth:
            return

        try:
            items = sorted(current.iterdir(), key=lambda x: (x.is_file(), x.name))
        except PermissionError:
            return

        for item in items:
            indent = "  " * depth
            rel = item.relative_to(root)
            if item.is_dir():
                entries.append(f"{indent}📁 {rel}/")
                self._list_recursive(root, item, max_depth, depth + 1, entries)
            else:
                size = item.stat().st_size
                size_str = self._format_size(size)
                entries.append(f"{indent}📄 {rel} ({size_str})")

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"
