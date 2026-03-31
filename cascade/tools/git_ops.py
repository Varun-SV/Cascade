"""Git operation tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cascade.core.approval import ApprovalMode, ApprovalRequest
from cascade.tools.base import BaseTool, ToolCapability, ToolResult, ToolRisk, ToolScope


def _truncate(text: str, max_chars: int = 10000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... (truncated, {len(text)} total chars)"


class GitTool(BaseTool):
    """Shared git helpers."""

    capabilities = (ToolCapability.GIT,)
    scope = ToolScope.GIT
    cache_ttl_seconds = 5

    def __init__(self, project_root: str = "."):
        self.project_root = str(Path(project_root).resolve())

    def _repo(self):
        try:
            import git
        except ImportError as exc:
            raise RuntimeError("gitpython not installed") from exc
        return git.Repo(self.project_root)


class GitStatusTool(GitTool):
    """Show git repository status."""

    name = "git_status"
    description = "Show the current git status including staged, modified, and untracked files."

    parameters_schema = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            repo = self._repo()
            lines: list[str] = []

            try:
                lines.append(f"Branch: {repo.active_branch.name}")
            except TypeError:
                lines.append("Branch: (detached HEAD)")

            if repo.head.is_valid():
                staged = [diff.a_path for diff in repo.index.diff("HEAD")]
            else:
                staged = []
            modified = [diff.a_path for diff in repo.index.diff(None)]
            untracked = repo.untracked_files

            if staged:
                lines.append(f"\nStaged ({len(staged)}):")
                lines.extend(f"  ✅ {path}" for path in staged[:20])
            if modified:
                lines.append(f"\nModified ({len(modified)}):")
                lines.extend(f"  📝 {path}" for path in modified[:20])
            if untracked:
                lines.append(f"\nUntracked ({len(untracked)}):")
                lines.extend(f"  ❓ {path}" for path in untracked[:20])
            if not any([staged, modified, untracked]):
                lines.append("\nWorking tree clean.")

            return ToolResult(output="\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, error=f"Git error: {e}")


class GitDiffTool(GitTool):
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
            "ref": {
                "type": "string",
                "description": "Optional ref or revision range to diff against.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum diff characters to return.",
            },
        },
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path")
        staged = kwargs.get("staged", False)
        ref = kwargs.get("ref")
        max_chars = kwargs.get("max_chars", 10000)

        try:
            repo = self._repo()
            if ref:
                args = [ref]
                if path:
                    args.extend(["--", path])
                diff = repo.git.diff(*args)
            elif staged:
                diff = repo.git.diff("--cached", path) if path else repo.git.diff("--cached")
            else:
                diff = repo.git.diff(path) if path else repo.git.diff()

            if not diff:
                return ToolResult(output="No changes to show.")
            return ToolResult(output=_truncate(diff, max_chars))
        except Exception as e:
            return ToolResult(success=False, error=f"Git error: {e}")


class GitLogTool(GitTool):
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
            "max_chars": {
                "type": "integer",
                "description": "Maximum log characters to return.",
            },
        },
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        count = kwargs.get("count", 10)
        oneline = kwargs.get("oneline", True)
        max_chars = kwargs.get("max_chars", 10000)

        try:
            repo = self._repo()
            if oneline:
                log = repo.git.log(f"-{count}", "--oneline", "--decorate")
            else:
                log = repo.git.log(f"-{count}", "--format=%h %s (%an, %ar)")
            if not log:
                return ToolResult(output="No commits yet.")
            return ToolResult(output=_truncate(log, max_chars))
        except Exception as e:
            return ToolResult(success=False, error=f"Git error: {e}")


class GitShowTool(GitTool):
    """Show a commit or blob."""

    name = "git_show"
    description = "Show a commit, tag, or a file at a revision."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ref": {
                "type": "string",
                "description": "Revision to show. Defaults to HEAD.",
            },
            "path": {
                "type": "string",
                "description": "Optional file path to show at the given revision.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return.",
            },
        },
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        ref = kwargs.get("ref", "HEAD")
        path = kwargs.get("path")
        max_chars = kwargs.get("max_chars", 10000)

        try:
            repo = self._repo()
            if path:
                output = repo.git.show(f"{ref}:{path}")
            else:
                output = repo.git.show(ref, "--stat")
            return ToolResult(output=_truncate(output, max_chars))
        except Exception as e:
            return ToolResult(success=False, error=f"Git error: {e}")


class GitAddTool(GitTool):
    """Stage changes."""

    name = "git_add"
    description = "Stage files in the git index."
    parameters_schema = {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Files to stage. If omitted, stages all changes.",
            }
        },
        "required": [],
    }
    risk_level = ToolRisk.APPROVAL_REQUIRED
    mutating = True

    def requires_approval(
        self, approval_mode: ApprovalMode, **kwargs: Any
    ) -> ApprovalRequest | None:
        if approval_mode in {ApprovalMode.AUTO, ApprovalMode.POWER_USER}:
            return None
        files = kwargs.get("files") or ["-A"]
        return ApprovalRequest(
            tool_name=self.name,
            reason="Staging files mutates the git index.",
            summary=" ".join(files),
        )

    async def dry_run(self, **kwargs: Any) -> ToolResult:
        files = kwargs.get("files") or ["all tracked changes"]
        return ToolResult(output=f"Would stage: {', '.join(files)}", metadata={"files": files})

    async def execute(self, **kwargs: Any) -> ToolResult:
        files = kwargs.get("files", [])
        try:
            repo = self._repo()
            if files:
                repo.index.add(files)
            else:
                repo.git.add("-A")
            return ToolResult(output="Staged changes successfully.")
        except Exception as e:
            return ToolResult(success=False, error=f"Git error: {e}")


class GitCommitTool(GitTool):
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
    risk_level = ToolRisk.APPROVAL_REQUIRED
    mutating = True

    def requires_approval(
        self, approval_mode: ApprovalMode, **kwargs: Any
    ) -> ApprovalRequest | None:
        if approval_mode in {ApprovalMode.AUTO, ApprovalMode.POWER_USER}:
            return None
        return ApprovalRequest(
            tool_name=self.name,
            reason="Creating a git commit mutates repository history.",
            summary=str(kwargs.get("message", "")),
        )

    async def dry_run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            output=f"Would create a git commit with message: {kwargs.get('message', '')}",
            metadata={"message": kwargs.get("message", ""), "files": kwargs.get("files", [])},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        message = kwargs.get("message", "")
        files = kwargs.get("files", [])

        if not message:
            return ToolResult(success=False, error="Commit message is required")

        try:
            repo = self._repo()
            if files:
                repo.index.add(files)
            else:
                repo.git.add("-A")

            commit = repo.index.commit(message)
            return ToolResult(output=f"Committed: {commit.hexsha[:8]} — {message}")
        except Exception as e:
            return ToolResult(success=False, error=f"Git error: {e}")


class GitCheckoutTool(GitTool):
    """Checkout a ref or create a branch."""

    name = "git_checkout"
    description = "Switch HEAD to another branch, tag, or commit."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ref": {"type": "string", "description": "Branch, tag, or commit to check out."},
            "create_branch": {
                "type": "boolean",
                "description": "Create a new branch with this name before checking it out.",
            },
            "start_point": {
                "type": "string",
                "description": "Optional start point when create_branch is true.",
            },
        },
        "required": ["ref"],
    }
    risk_level = ToolRisk.APPROVAL_REQUIRED
    mutating = True
    reversible = False

    def requires_approval(
        self, approval_mode: ApprovalMode, **kwargs: Any
    ) -> ApprovalRequest | None:
        if approval_mode in {ApprovalMode.AUTO, ApprovalMode.POWER_USER}:
            return None
        ref = kwargs.get("ref", "")
        return ApprovalRequest(
            tool_name=self.name,
            reason="Checking out a ref changes HEAD and may affect the working tree.",
            summary=str(ref),
        )

    async def dry_run(self, **kwargs: Any) -> ToolResult:
        action = "create and check out" if kwargs.get("create_branch", False) else "check out"
        return ToolResult(
            output=f"Would {action} {kwargs.get('ref', '')}",
            metadata={"ref": kwargs.get("ref", ""), "create_branch": kwargs.get("create_branch", False)},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        ref = kwargs.get("ref", "")
        create_branch = kwargs.get("create_branch", False)
        start_point = kwargs.get("start_point")

        try:
            repo = self._repo()
            if create_branch:
                if start_point:
                    repo.git.checkout("-b", ref, start_point)
                else:
                    repo.git.checkout("-b", ref)
            else:
                repo.git.checkout(ref)
            return ToolResult(output=f"Checked out {ref}")
        except Exception as e:
            return ToolResult(success=False, error=f"Git error: {e}")
