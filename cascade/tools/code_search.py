"""Code search tools — grep and file finding."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from cascade.tools.base import BaseTool, Tier, ToolResult


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
    allowed_tiers = {Tier.T1, Tier.T2, Tier.T3}

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

        # Try ripgrep first
        try:
            return await self._rg_search(query, str(search_path), include, case_insensitive)
        except FileNotFoundError:
            return await self._python_search(query, search_path, include, case_insensitive)

    async def _rg_search(
        self, query: str, path: str, include: str, case_insensitive: bool
    ) -> ToolResult:
        """Search using ripgrep."""
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
        stdout, stderr = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace").strip()

        if not output:
            return ToolResult(output="No matches found.")
        return ToolResult(output=output)

    async def _python_search(
        self, query: str, path: Path, include: str, case_insensitive: bool
    ) -> ToolResult:
        """Fallback Python-based search."""
        import fnmatch

        results: list[str] = []
        search_query = query.lower() if case_insensitive else query
        max_results = 50

        for root, dirs, files in os.walk(path):
            # Skip hidden and common ignore dirs
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__", ".git"}]

            for fname in files:
                if include and not fnmatch.fnmatch(fname, include):
                    continue

                fpath = Path(root) / fname
                try:
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(content.splitlines(), 1):
                        check_line = line.lower() if case_insensitive else line
                        if search_query in check_line:
                            rel = fpath.relative_to(self.project_root)
                            results.append(f"{rel}:{i}: {line.strip()}")
                            if len(results) >= max_results:
                                break
                except (PermissionError, UnicodeDecodeError):
                    continue

                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break

        if not results:
            return ToolResult(output="No matches found.")
        return ToolResult(output="\n".join(results))


class FindFilesTool(BaseTool):
    """Find files by name pattern."""

    name = "find_files"
    description = (
        "Find files and directories matching a name pattern. "
        "Supports glob patterns like '*.py', 'test_*', etc."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match file names (e.g., '*.py', 'test_*').",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Defaults to project root.",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum directory depth to search. Default is 10.",
            },
        },
        "required": ["pattern"],
    }
    allowed_tiers = {Tier.T1, Tier.T2, Tier.T3}

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()

    async def execute(self, **kwargs: Any) -> ToolResult:
        pattern = kwargs.get("pattern", "")
        path = kwargs.get("path", ".") or "."
        max_depth = kwargs.get("max_depth", 10)

        if not pattern:
            return ToolResult(success=False, error="No pattern provided")

        search_path = Path(path)
        if not search_path.is_absolute():
            search_path = self.project_root / search_path

        if not search_path.exists():
            return ToolResult(success=False, error=f"Path not found: {path}")

        results: list[str] = []
        max_results = 50
        self._find_recursive(search_path, pattern, max_depth, 0, results, max_results)

        if not results:
            return ToolResult(output=f"No files matching '{pattern}' found.")
        return ToolResult(output="\n".join(results))

    def _find_recursive(
        self,
        current: Path,
        pattern: str,
        max_depth: int,
        depth: int,
        results: list[str],
        max_results: int,
    ) -> None:
        if depth > max_depth or len(results) >= max_results:
            return

        try:
            for item in sorted(current.iterdir()):
                if item.name.startswith("."):
                    continue
                if len(results) >= max_results:
                    break

                import fnmatch
                if fnmatch.fnmatch(item.name, pattern):
                    try:
                        rel = item.relative_to(self.project_root)
                    except ValueError:
                        rel = item
                    prefix = "📁" if item.is_dir() else "📄"
                    results.append(f"{prefix} {rel}")

                if item.is_dir() and item.name not in {"node_modules", "__pycache__", ".git"}:
                    self._find_recursive(item, pattern, max_depth, depth + 1, results, max_results)
        except PermissionError:
            pass
