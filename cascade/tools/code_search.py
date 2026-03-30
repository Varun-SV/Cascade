"""Code search tools."""

from __future__ import annotations

import asyncio
import fnmatch
import os
from pathlib import Path
from typing import Any

from cascade.tools.base import BaseTool, ToolCapability, ToolResult


class GrepSearchTool(BaseTool):
    """Search for text patterns in files."""

    name = "grep_search"
    description = (
        "Search for a text pattern across files in the project. "
        "Uses ripgrep (rg) if available, otherwise falls back to Python search. "
        "Returns matching lines with file names and line numbers."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The text pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": "Directory or file to search in. Defaults to project root.",
            },
            "include": {
                "type": "string",
                "description": "Glob pattern to filter files (e.g., '*.py').",
            },
            "case_insensitive": {
                "type": "boolean",
                "description": "Whether to search case-insensitively.",
            },
        },
        "required": ["query"],
    }
    capabilities = (ToolCapability.READ,)

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "")
        path = kwargs.get("path", ".") or "."
        include = kwargs.get("include", "")
        case_insensitive = kwargs.get("case_insensitive", False)

        if not query:
            return ToolResult(success=False, error="No search query provided")

        search_path = Path(path)
        if not search_path.is_absolute():
            search_path = self.project_root / search_path
        search_path = search_path.resolve()

        try:
            search_path.relative_to(self.project_root)
        except ValueError:
            return ToolResult(success=False, error=f"Access denied: {search_path}")

        try:
            return await self._rg_search(query, str(search_path), include, case_insensitive)
        except FileNotFoundError:
            return await self._python_search(query, search_path, include, case_insensitive)

    async def _rg_search(
        self, query: str, path: str, include: str, case_insensitive: bool
    ) -> ToolResult:
        cmd = ["rg", "--line-number", "--no-heading", "--max-count=50"]
        if case_insensitive:
            cmd.append("-i")
        if include:
            cmd.extend(["--glob", include])
        cmd.extend([query, path])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace").strip()
        if not output:
            return ToolResult(output="No matches found.")
        return ToolResult(output=output)

    async def _python_search(
        self, query: str, path: Path, include: str, case_insensitive: bool
    ) -> ToolResult:
        results: list[str] = []
        search_query = query.lower() if case_insensitive else query

        for root, dirs, files in os.walk(path):
            dirs[:] = [
                directory
                for directory in dirs
                if not directory.startswith(".")
                and directory not in {"node_modules", "__pycache__", ".git"}
            ]

            for filename in files:
                if include and not fnmatch.fnmatch(filename, include):
                    continue

                candidate = Path(root) / filename
                try:
                    content = candidate.read_text(encoding="utf-8", errors="ignore")
                except (PermissionError, UnicodeDecodeError):
                    continue

                for line_number, line in enumerate(content.splitlines(), start=1):
                    haystack = line.lower() if case_insensitive else line
                    if search_query in haystack:
                        rel = candidate.relative_to(self.project_root)
                        results.append(f"{rel}:{line_number}: {line.strip()}")
                        if len(results) >= 50:
                            return ToolResult(output="\n".join(results))

        if not results:
            return ToolResult(output="No matches found.")
        return ToolResult(output="\n".join(results))
