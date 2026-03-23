"""Git operation tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cascade.tools.base import BaseTool, Tier, ToolResult


class GitStatusTool(BaseTool):
    """Show git repository status."""

    name = "git_status"
    description = "Show the current git status including staged, modified, and untracked files."
    parameters_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    allowed_tiers = {Tier.T1, Tier.T2, Tier.T3}

    def __init__(self, project_root: str = "."):
        self.project_root = project_root

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            import git

            repo = git.Repo(self.project_root)
            status_lines: list[str] = []

            # Branch info
            try:
                branch = repo.active_branch.name
                status_lines.append(f"Branch: {branch}")
            except TypeError:
                status_lines.append("Branch: (detached HEAD)")

            # Changed files
            staged = [d.a_path for d in repo.index.diff("HEAD")] if repo.head.is_valid() else []
            modified = [d.a_path for d in repo.index.diff(None)]
            untracked = repo.untracked_files

            if staged:
                status_lines.append(f"\nStaged ({len(staged)}):")
                for f in staged[:20]:
                    status_lines.append(f"  ✅ {f}")
            if modified:
                status_lines.append(f"\nModified ({len(modified)}):")
                for f in modified[:20]:
                    status_lines.append(f"  📝 {f}")
            if untracked:
                status_lines.append(f"\nUntracked ({len(untracked)}):")
                for f in untracked[:20]:
                    status_lines.append(f"  ❓ {f}")

            if not staged and not modified and not untracked:
                status_lines.append("\nWorking tree clean.")

            return ToolResult(output="\n".join(status_lines))
        except ImportError:
            return ToolResult(success=False, error="gitpython not installed")
        except Exception as e:
            return ToolResult(success=False, error=f"Git error: {e}")


class GitDiffTool(BaseTool):
    """Show git diff for changed files."""

    name = "git_diff"
    description = "Show the diff of modified files. Optionally specify a file path."
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Optional file path to diff. If omitted, diffs all changed files.",
            },
            "staged": {
                "type": "boolean",
                "description": "If true, show staged diff. Default is false.",
            },
        },
        "required": [],
    }
    allowed_tiers = {Tier.T1, Tier.T2, Tier.T3}

    def __init__(self, project_root: str = "."):
        self.project_root = project_root

    async def execute(self, **kwargs: Any) -> ToolResult:
        file_path = kwargs.get("path")
        staged = kwargs.get("staged", False)

        try:
            import git

            repo = git.Repo(self.project_root)

            if staged:
                diff = repo.git.diff("--cached", file_path) if file_path else repo.git.diff("--cached")
            else:
                diff = repo.git.diff(file_path) if file_path else repo.git.diff()

            if not diff:
                return ToolResult(output="No changes to show.")

            # Truncate very long diffs
            if len(diff) > 10000:
                diff = diff[:10000] + "\n... (diff truncated)"

            return ToolResult(output=diff)
        except ImportError:
            return ToolResult(success=False, error="gitpython not installed")
        except Exception as e:
            return ToolResult(success=False, error=f"Git error: {e}")


class GitLogTool(BaseTool):
    """Show recent git commit log."""

    name = "git_log"
    description = "Show recent git commit history."
    parameters_schema = {
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "Number of commits to show. Default is 10.",
            },
            "oneline": {
                "type": "boolean",
                "description": "Show condensed one-line format. Default is true.",
            },
        },
        "required": [],
    }
    allowed_tiers = {Tier.T1, Tier.T2, Tier.T3}

    def __init__(self, project_root: str = "."):
        self.project_root = project_root

    async def execute(self, **kwargs: Any) -> ToolResult:
        count = kwargs.get("count", 10)
        oneline = kwargs.get("oneline", True)

        try:
            import git

            repo = git.Repo(self.project_root)

            if oneline:
                log = repo.git.log(f"-{count}", "--oneline", "--decorate")
            else:
                log = repo.git.log(f"-{count}", "--format=%h %s (%an, %ar)")

            if not log:
                return ToolResult(output="No commits yet.")
            return ToolResult(output=log)
        except ImportError:
            return ToolResult(success=False, error="gitpython not installed")
        except Exception as e:
            return ToolResult(success=False, error=f"Git error: {e}")


class GitCommitTool(BaseTool):
    """Create a git commit."""

    name = "git_commit"
    description = "Stage files and create a git commit. Optionally stage all changed files."
    parameters_schema = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Commit message.",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of files to stage. If empty, stages all changed files.",
            },
        },
        "required": ["message"],
    }
    allowed_tiers = {Tier.T1, Tier.T2}  # T3 cannot commit

    def __init__(self, project_root: str = "."):
        self.project_root = project_root

    async def execute(self, **kwargs: Any) -> ToolResult:
        message = kwargs.get("message", "")
        files = kwargs.get("files", [])

        if not message:
            return ToolResult(success=False, error="Commit message is required")

        try:
            import git

            repo = git.Repo(self.project_root)

            if files:
                repo.index.add(files)
            else:
                repo.git.add("-A")

            commit = repo.index.commit(message)
            return ToolResult(
                output=f"Committed: {commit.hexsha[:8]} — {message}"
            )
        except ImportError:
            return ToolResult(success=False, error="gitpython not installed")
        except Exception as e:
            return ToolResult(success=False, error=f"Git error: {e}")
