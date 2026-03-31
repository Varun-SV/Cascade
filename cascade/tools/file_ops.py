"""File operation tools — read, search, edit, move, and patch files."""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cascade.core.approval import ApprovalMode, ApprovalRequest
from cascade.tools.base import BaseTool, ToolCapability, ToolResult, ToolRisk, ToolScope


class ProjectPathTool(BaseTool):
    """Base class for tools that operate inside the project sandbox."""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()

    def _resolve_path(self, path: str, allow_missing: bool = False) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.project_root / candidate
        candidate = candidate.resolve()

        try:
            candidate.relative_to(self.project_root)
        except ValueError:
            raise PermissionError(f"Access denied: {candidate} is outside project root")
        if not allow_missing and not candidate.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        return candidate

    def _relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.project_root))
        except ValueError:
            return str(path)


class ReadFileTool(ProjectPathTool):
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
            "max_chars": {
                "type": "integer",
                "description": "Optional maximum number of characters to return.",
            },
        },
        "required": ["path"],
    }
    capabilities = (ToolCapability.READ,)
    scope = ToolScope.FILE
    cache_ttl_seconds = 5

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        start_line = kwargs.get("start_line")
        end_line = kwargs.get("end_line")
        max_chars = kwargs.get("max_chars")

        try:
            resolved = self._resolve_path(path)
            if not resolved.is_file():
                return ToolResult(success=False, error=f"Not a file: {path}")

            content = resolved.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines(keepends=True)

            if start_line or end_line:
                start = max((start_line or 1) - 1, 0)
                end = end_line or len(lines)
                content = "".join(lines[start:end])

            if max_chars and len(content) > max_chars:
                content = content[:max_chars] + f"\n... (truncated, {len(content)} total chars)"

            return ToolResult(output=content)
        except PermissionError as e:
            return ToolResult(success=False, error=str(e))
        except FileNotFoundError:
            return ToolResult(success=False, error=f"File not found: {path}")
        except Exception as e:
            return ToolResult(success=False, error=f"Error reading file: {e}")


class ReadFilesTool(ProjectPathTool):
    """Read multiple files in one tool call."""

    name = "read_files"
    description = (
        "Read multiple files and return them in a single response with file headers. "
        "Useful for gathering context from several files at once."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of file paths to read.",
            },
            "max_chars_per_file": {
                "type": "integer",
                "description": "Optional maximum characters to return for each file.",
            },
        },
        "required": ["paths"],
    }
    capabilities = (ToolCapability.READ,)
    scope = ToolScope.FILE
    cache_ttl_seconds = 5

    async def execute(self, **kwargs: Any) -> ToolResult:
        paths = kwargs.get("paths", [])
        max_chars_per_file = kwargs.get("max_chars_per_file")

        if not paths:
            return ToolResult(success=False, error="No file paths provided")

        sections: list[str] = []
        for path in paths:
            try:
                resolved = self._resolve_path(path)
                if not resolved.is_file():
                    sections.append(f"==> {path} <==\nERROR: Not a file")
                    continue

                content = resolved.read_text(encoding="utf-8", errors="replace")
                if max_chars_per_file and len(content) > max_chars_per_file:
                    content = (
                        content[:max_chars_per_file]
                        + f"\n... (truncated, {len(content)} total chars)"
                    )
                sections.append(f"==> {path} <==\n{content}")
            except Exception as e:
                sections.append(f"==> {path} <==\nERROR: {e}")

        return ToolResult(output="\n\n".join(sections))


class WriteFileTool(ProjectPathTool):
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
    capabilities = (ToolCapability.WRITE,)
    risk_level = ToolRisk.APPROVAL_REQUIRED
    scope = ToolScope.FILE
    mutating = True

    def requires_approval(
        self, approval_mode: ApprovalMode, **kwargs: Any
    ) -> ApprovalRequest | None:
        if approval_mode in {ApprovalMode.AUTO, ApprovalMode.POWER_USER}:
            return None
        return ApprovalRequest(
            tool_name=self.name,
            reason="Writing files mutates the repository.",
            summary=str(kwargs.get("path", "")),
        )

    async def dry_run(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        content = kwargs.get("content", "")
        return ToolResult(
            output=f"Would write {len(content)} characters to {path}",
            metadata={"path": path, "size": len(content)},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        content = kwargs.get("content", "")

        try:
            resolved = self._resolve_path(path, allow_missing=True)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return ToolResult(output=f"Successfully wrote {len(content)} characters to {path}")
        except PermissionError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Error writing file: {e}")


class EditFileTool(ProjectPathTool):
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
    capabilities = (ToolCapability.WRITE,)
    risk_level = ToolRisk.APPROVAL_REQUIRED
    scope = ToolScope.FILE
    mutating = True

    def requires_approval(
        self, approval_mode: ApprovalMode, **kwargs: Any
    ) -> ApprovalRequest | None:
        if approval_mode in {ApprovalMode.AUTO, ApprovalMode.POWER_USER}:
            return None
        return ApprovalRequest(
            tool_name=self.name,
            reason="Editing files mutates the repository.",
            summary=str(kwargs.get("path", "")),
        )

    async def dry_run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            output=f"Would edit {kwargs.get('path', '')} by replacing a specific target string.",
            metadata={"path": kwargs.get("path", "")},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        target = kwargs.get("target", "")
        replacement = kwargs.get("replacement", "")

        try:
            resolved = self._resolve_path(path)
            if not resolved.is_file():
                return ToolResult(success=False, error=f"Not a file: {path}")

            content = resolved.read_text(encoding="utf-8")
            if target not in content:
                return ToolResult(success=False, error=f"Target text not found in {path}")

            count = content.count(target)
            resolved.write_text(content.replace(target, replacement, 1), encoding="utf-8")
            return ToolResult(output=f"Replaced 1 of {count} occurrence(s) in {path}")
        except PermissionError as e:
            return ToolResult(success=False, error=str(e))
        except FileNotFoundError:
            return ToolResult(success=False, error=f"File not found: {path}")
        except Exception as e:
            return ToolResult(success=False, error=f"Error editing file: {e}")


class SearchReplaceTool(ProjectPathTool):
    """Perform literal or regex-based replacements."""

    name = "search_replace"
    description = (
        "Replace text in a file using either a literal search string or a regex pattern. "
        "Supports replacing the Nth occurrence or a bounded number of matches."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to edit."},
            "search": {"type": "string", "description": "Literal text or regex pattern."},
            "replacement": {"type": "string", "description": "Replacement text."},
            "regex": {
                "type": "boolean",
                "description": "Interpret `search` as a regular expression.",
            },
            "occurrence": {
                "type": "integer",
                "description": "Optional 1-indexed occurrence to replace.",
            },
            "max_replacements": {
                "type": "integer",
                "description": "Maximum matches to replace when occurrence is not provided.",
            },
        },
        "required": ["path", "search", "replacement"],
    }
    capabilities = (ToolCapability.WRITE,)
    risk_level = ToolRisk.APPROVAL_REQUIRED
    scope = ToolScope.FILE
    mutating = True

    def requires_approval(
        self, approval_mode: ApprovalMode, **kwargs: Any
    ) -> ApprovalRequest | None:
        if approval_mode in {ApprovalMode.AUTO, ApprovalMode.POWER_USER}:
            return None
        return ApprovalRequest(
            tool_name=self.name,
            reason="Search-and-replace mutates file contents.",
            summary=str(kwargs.get("path", "")),
        )

    async def dry_run(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        search = kwargs.get("search", "")
        replacement = kwargs.get("replacement", "")
        return ToolResult(
            output=f"Would replace occurrences of {search!r} with {replacement!r} in {path}",
            metadata={"path": path},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        search = kwargs.get("search", "")
        replacement = kwargs.get("replacement", "")
        use_regex = bool(kwargs.get("regex", False))
        occurrence = kwargs.get("occurrence")
        max_replacements = kwargs.get("max_replacements", 1)

        if occurrence is not None and occurrence < 1:
            return ToolResult(success=False, error="occurrence must be >= 1")
        if max_replacements is not None and max_replacements < 1:
            return ToolResult(success=False, error="max_replacements must be >= 1")

        try:
            resolved = self._resolve_path(path)
            content = resolved.read_text(encoding="utf-8")

            if use_regex:
                new_content, replaced = self._replace_regex(
                    content, search, replacement, occurrence, max_replacements
                )
            else:
                new_content, replaced = self._replace_literal(
                    content, search, replacement, occurrence, max_replacements
                )

            if replaced == 0:
                return ToolResult(success=False, error=f"No matches found in {path}")

            resolved.write_text(new_content, encoding="utf-8")
            return ToolResult(output=f"Replaced {replaced} occurrence(s) in {path}")
        except re.error as e:
            return ToolResult(success=False, error=f"Invalid regex: {e}")
        except Exception as e:
            return ToolResult(success=False, error=f"Error applying search_replace: {e}")

    def _replace_literal(
        self,
        content: str,
        search: str,
        replacement: str,
        occurrence: int | None,
        max_replacements: int | None,
    ) -> tuple[str, int]:
        if not search:
            raise ValueError("search cannot be empty")

        total_matches = content.count(search)
        if total_matches == 0:
            return content, 0

        if occurrence is not None:
            index = -1
            start = 0
            for _ in range(occurrence):
                index = content.find(search, start)
                if index == -1:
                    return content, 0
                start = index + len(search)
            return (
                content[:index] + replacement + content[index + len(search) :],
                1,
            )

        limit = max_replacements if max_replacements is not None else total_matches
        return content.replace(search, replacement, limit), min(total_matches, limit)

    def _replace_regex(
        self,
        content: str,
        search: str,
        replacement: str,
        occurrence: int | None,
        max_replacements: int | None,
    ) -> tuple[str, int]:
        pattern = re.compile(search, re.MULTILINE)
        matches = list(pattern.finditer(content))
        if not matches:
            return content, 0

        if occurrence is not None:
            if occurrence > len(matches):
                return content, 0
            target = matches[occurrence - 1]
            replaced = pattern.sub(replacement, target.group(0), count=1)
            return content[: target.start()] + replaced + content[target.end() :], 1

        limit = max_replacements if max_replacements is not None else len(matches)
        return pattern.subn(replacement, content, count=limit)


@dataclass
class _PatchHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[tuple[str, str]]


@dataclass
class _PatchFile:
    old_path: str | None
    new_path: str | None
    hunks: list[_PatchHunk]


class ApplyPatchTool(ProjectPathTool):
    """Apply a unified diff across one or more files atomically."""

    name = "apply_patch"
    description = (
        "Apply a unified diff patch across one or more files. "
        "The patch is applied atomically: if any hunk fails, no files are changed."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "patch": {
                "type": "string",
                "description": "Unified diff patch content.",
            }
        },
        "required": ["patch"],
    }
    capabilities = (ToolCapability.WRITE,)
    risk_level = ToolRisk.APPROVAL_REQUIRED
    scope = ToolScope.FILE
    mutating = True

    def requires_approval(
        self, approval_mode: ApprovalMode, **kwargs: Any
    ) -> ApprovalRequest | None:
        if approval_mode in {ApprovalMode.AUTO, ApprovalMode.POWER_USER}:
            return None
        return ApprovalRequest(
            tool_name=self.name,
            reason="Applying a patch can mutate multiple files at once.",
            summary="apply_patch",
        )

    async def dry_run(self, **kwargs: Any) -> ToolResult:
        patch_text = kwargs.get("patch", "")
        touched = patch_text.count("\n--- ")
        return ToolResult(
            output=f"Would apply a patch touching approximately {max(touched, 1)} file(s).",
            metadata={"touched_files_estimate": max(touched, 1)},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        patch_text = kwargs.get("patch", "")
        if not patch_text.strip():
            return ToolResult(success=False, error="Patch content is required")

        try:
            files = self._parse_patch(patch_text)
            planned_writes: dict[Path, str | None] = {}

            for file_patch in files:
                target_path, new_content = self._apply_file_patch(file_patch)
                planned_writes[target_path] = new_content

            for path, new_content in planned_writes.items():
                if new_content is None:
                    if path.is_dir():
                        shutil.rmtree(path)
                    elif path.exists():
                        path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(new_content, encoding="utf-8")

            return ToolResult(output=f"Applied patch touching {len(planned_writes)} file(s)")
        except Exception as e:
            return ToolResult(success=False, error=f"Patch apply failed: {e}")

    def _parse_patch(self, patch_text: str) -> list[_PatchFile]:
        lines = patch_text.splitlines()
        files: list[_PatchFile] = []
        index = 0

        while index < len(lines):
            line = lines[index]
            if line.startswith(("diff --git ", "index ", "new file mode ", "deleted file mode ")):
                index += 1
                continue
            if not line.startswith("--- "):
                index += 1
                continue

            old_path = self._normalize_patch_path(line[4:])
            index += 1
            if index >= len(lines) or not lines[index].startswith("+++ "):
                raise ValueError("Malformed patch: missing +++ header")
            new_path = self._normalize_patch_path(lines[index][4:])
            index += 1

            hunks: list[_PatchHunk] = []
            while index < len(lines):
                current = lines[index]
                if current.startswith(("diff --git ", "--- ")):
                    break
                if not current.startswith("@@ "):
                    index += 1
                    continue

                match = re.match(
                    r"@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
                    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@",
                    current,
                )
                if not match:
                    raise ValueError(f"Malformed hunk header: {current}")

                old_count = int(match.group("old_count") or "1")
                new_count = int(match.group("new_count") or "1")
                hunk = _PatchHunk(
                    old_start=int(match.group("old_start")),
                    old_count=old_count,
                    new_start=int(match.group("new_start")),
                    new_count=new_count,
                    lines=[],
                )
                index += 1

                while index < len(lines):
                    hunk_line = lines[index]
                    if hunk_line.startswith(("diff --git ", "--- ", "@@ ")):
                        break
                    if hunk_line.startswith("\\ No newline at end of file"):
                        index += 1
                        continue
                    if not hunk_line:
                        raise ValueError("Malformed patch line: missing hunk marker")

                    marker = hunk_line[0]
                    if marker not in {" ", "+", "-"}:
                        raise ValueError(f"Malformed patch line: {hunk_line}")
                    hunk.lines.append((marker, hunk_line[1:]))
                    index += 1

                hunks.append(hunk)

            files.append(_PatchFile(old_path=old_path, new_path=new_path, hunks=hunks))

        if not files:
            raise ValueError("No file hunks were found in the patch")
        return files

    def _normalize_patch_path(self, value: str) -> str | None:
        path = value.strip().split("\t", 1)[0]
        if path == "/dev/null":
            return None
        if path.startswith(("a/", "b/")):
            path = path[2:]
        return path

    def _apply_file_patch(self, file_patch: _PatchFile) -> tuple[Path, str | None]:
        if file_patch.old_path and file_patch.new_path and file_patch.old_path != file_patch.new_path:
            raise ValueError("Renames are not supported by apply_patch; use move_path instead.")

        target_str = file_patch.new_path or file_patch.old_path
        if target_str is None:
            raise ValueError("Malformed patch: file path missing")

        target_path = self._resolve_path(target_str, allow_missing=True)
        original = ""
        trailing_newline = True

        if file_patch.old_path is not None:
            source_path = self._resolve_path(file_patch.old_path)
            if not source_path.is_file():
                raise ValueError(f"Patch target is not a file: {file_patch.old_path}")
            original = source_path.read_text(encoding="utf-8")
            trailing_newline = original.endswith("\n") or original == ""

        original_lines = original.splitlines()
        cursor = 0
        output_lines: list[str] = []

        for hunk in file_patch.hunks:
            start = max(hunk.old_start - 1, 0)
            if start < cursor:
                raise ValueError(f"Overlapping hunks for {target_str}")

            output_lines.extend(original_lines[cursor:start])
            source_index = start

            for marker, text in hunk.lines:
                if marker == " ":
                    if source_index >= len(original_lines) or original_lines[source_index] != text:
                        raise ValueError(f"Context mismatch in {target_str}")
                    output_lines.append(original_lines[source_index])
                    source_index += 1
                elif marker == "-":
                    if source_index >= len(original_lines) or original_lines[source_index] != text:
                        raise ValueError(f"Removal mismatch in {target_str}")
                    source_index += 1
                elif marker == "+":
                    output_lines.append(text)

            cursor = source_index

        output_lines.extend(original_lines[cursor:])

        if file_patch.new_path is None:
            return target_path, None

        new_content = "\n".join(output_lines)
        if output_lines and (file_patch.old_path is None or trailing_newline):
            new_content += "\n"
        return target_path, new_content


class MovePathTool(ProjectPathTool):
    """Move or rename a file or directory."""

    name = "move_path"
    description = "Move or rename a file or directory within the project root."
    parameters_schema = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source path."},
            "destination": {"type": "string", "description": "Destination path."},
            "overwrite": {
                "type": "boolean",
                "description": "Overwrite the destination if it already exists.",
            },
        },
        "required": ["source", "destination"],
    }
    capabilities = (ToolCapability.WRITE,)
    risk_level = ToolRisk.APPROVAL_REQUIRED
    scope = ToolScope.FILE
    mutating = True

    def requires_approval(
        self, approval_mode: ApprovalMode, **kwargs: Any
    ) -> ApprovalRequest | None:
        if approval_mode in {ApprovalMode.AUTO, ApprovalMode.POWER_USER}:
            return None
        return ApprovalRequest(
            tool_name=self.name,
            reason="Moving files mutates the repository layout.",
            summary=f"{kwargs.get('source', '')} -> {kwargs.get('destination', '')}",
        )

    async def dry_run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            output=f"Would move {kwargs.get('source', '')} -> {kwargs.get('destination', '')}",
            metadata={"source": kwargs.get("source", ""), "destination": kwargs.get("destination", "")},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        source = kwargs.get("source", "")
        destination = kwargs.get("destination", "")
        overwrite = bool(kwargs.get("overwrite", False))

        try:
            src = self._resolve_path(source)
            dest = self._resolve_path(destination, allow_missing=True)

            if dest.exists():
                if not overwrite:
                    return ToolResult(success=False, error=f"Destination already exists: {destination}")
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()

            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            return ToolResult(output=f"Moved {source} -> {destination}")
        except Exception as e:
            return ToolResult(success=False, error=f"Error moving path: {e}")


class DeletePathTool(ProjectPathTool):
    """Delete a file or directory."""

    name = "delete_path"
    description = "Delete a file or directory from the project root."
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to delete."},
            "recursive": {
                "type": "boolean",
                "description": "Recursively delete directories. Default is true.",
            },
        },
        "required": ["path"],
    }
    capabilities = (ToolCapability.WRITE,)
    risk_level = ToolRisk.APPROVAL_REQUIRED
    scope = ToolScope.FILE
    mutating = True
    reversible = False

    def requires_approval(
        self, approval_mode: ApprovalMode, **kwargs: Any
    ) -> ApprovalRequest | None:
        if approval_mode in {ApprovalMode.AUTO, ApprovalMode.POWER_USER}:
            return None
        return ApprovalRequest(
            tool_name=self.name,
            reason="Deleting files is destructive.",
            summary=str(kwargs.get("path", "")),
        )

    async def dry_run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            output=f"Would delete {kwargs.get('path', '')}",
            metadata={"path": kwargs.get("path", "")},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "")
        recursive = kwargs.get("recursive", True)

        try:
            resolved = self._resolve_path(path)
            if resolved.is_dir():
                if recursive:
                    shutil.rmtree(resolved)
                else:
                    resolved.rmdir()
            else:
                resolved.unlink()
            return ToolResult(output=f"Deleted {path}")
        except Exception as e:
            return ToolResult(success=False, error=f"Error deleting path: {e}")


class ListDirectoryTool(ProjectPathTool):
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
    capabilities = (ToolCapability.READ,)
    scope = ToolScope.FILE
    cache_ttl_seconds = 5

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", ".") or "."
        max_depth = kwargs.get("max_depth", 1)

        try:
            resolved = self._resolve_path(path)
            if not resolved.is_dir():
                return ToolResult(success=False, error=f"Not a directory: {path}")

            entries: list[str] = []
            self._list_recursive(resolved, resolved, max_depth, 0, entries)
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
            items = sorted(current.iterdir(), key=lambda entry: (entry.is_file(), entry.name))
        except PermissionError:
            return

        for item in items:
            indent = "  " * depth
            rel = item.relative_to(root)
            if item.is_dir():
                entries.append(f"{indent}📁 {rel}/")
                self._list_recursive(root, item, max_depth, depth + 1, entries)
            else:
                entries.append(f"{indent}📄 {rel} ({self._format_size(item.stat().st_size)})")

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"


class GlobFilesTool(ProjectPathTool):
    """Find files using glob patterns."""

    name = "glob_files"
    description = (
        "Find files or directories using glob patterns like '*.py' or '**/*.md'. "
        "Returns project-relative paths."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern to match."},
            "path": {
                "type": "string",
                "description": "Directory to search from. Defaults to project root.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum results to return. Default is 200.",
            },
        },
        "required": ["pattern"],
    }
    capabilities = (ToolCapability.READ,)
    scope = ToolScope.FILE
    cache_ttl_seconds = 5

    async def execute(self, **kwargs: Any) -> ToolResult:
        pattern = kwargs.get("pattern", "")
        path = kwargs.get("path", ".") or "."
        max_results = kwargs.get("max_results", 200)

        if not pattern:
            return ToolResult(success=False, error="No glob pattern provided")

        try:
            search_root = self._resolve_path(path)
            iterator = search_root.glob(pattern)
            results: list[str] = []
            for match in iterator:
                if match.name.startswith("."):
                    continue
                results.append(self._relative(match))
                if len(results) >= max_results:
                    break

            if not results:
                return ToolResult(output=f"No files matching '{pattern}' found.")
            return ToolResult(output="\n".join(sorted(results)))
        except Exception as e:
            return ToolResult(success=False, error=f"Error globbing files: {e}")


class FindFilesTool(ProjectPathTool):
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
    capabilities = (ToolCapability.READ,)
    scope = ToolScope.FILE
    cache_ttl_seconds = 5

    async def execute(self, **kwargs: Any) -> ToolResult:
        pattern = kwargs.get("pattern", "")
        path = kwargs.get("path", ".") or "."
        max_depth = kwargs.get("max_depth", 10)

        if not pattern:
            return ToolResult(success=False, error="No pattern provided")

        try:
            search_path = self._resolve_path(path)
            if not search_path.is_dir():
                return ToolResult(success=False, error=f"Not a directory: {path}")

            results: list[str] = []
            self._find_recursive(search_path, pattern, max_depth, 0, results, 50)
            if not results:
                return ToolResult(output=f"No files matching '{pattern}' found.")
            return ToolResult(output="\n".join(results))
        except Exception as e:
            return ToolResult(success=False, error=f"Error finding files: {e}")

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
            items = sorted(current.iterdir())
        except PermissionError:
            return

        for item in items:
            if item.name.startswith("."):
                continue
            if len(results) >= max_results:
                break

            if fnmatch.fnmatch(item.name, pattern):
                prefix = "📁" if item.is_dir() else "📄"
                results.append(f"{prefix} {self._relative(item)}")

            if item.is_dir() and item.name not in {"node_modules", "__pycache__", ".git"}:
                self._find_recursive(item, pattern, max_depth, depth + 1, results, max_results)
