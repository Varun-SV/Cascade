"""Shell command and process execution tools."""

from __future__ import annotations

import asyncio
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cascade.core.approval import ApprovalMode, ApprovalRequest
from cascade.tools.base import BaseTool, ToolCapability, ToolResult, ToolRisk, ToolScope

SAFE_COMMAND_PREFIXES = [
    # Read-only / inspection
    ("pwd",),
    ("ls",),
    ("cat",),
    ("head",),
    ("tail",),
    ("sed",),
    ("awk",),
    ("grep",),
    ("rg",),
    ("find",),
    ("wc",),
    ("sort",),
    ("uniq",),
    ("cut",),
    ("stat",),
    ("which",),
    ("echo",),
    ("env",),
    ("printenv",),
    ("tree",),
    ("file",),
    ("du",),
    ("df",),
    # File creation (non-destructive)
    ("mkdir",),
    ("touch",),
    ("cp",),
    # Git (read-only)
    ("git", "status"),
    ("git", "diff"),
    ("git", "log"),
    ("git", "show"),
    ("git", "branch"),
    ("git", "remote"),
    ("git", "tag"),
    # Python
    ("python",),
    ("python3",),
    ("pip",),
    ("pip3",),
    ("pytest",),
    ("ruff",),
    ("black",),
    ("mypy",),
    ("flake8",),
    ("uvicorn",),
    # Node / JS
    ("node",),
    ("npm",),
    ("npx",),
    ("pnpm",),
    ("yarn",),
    ("bun",),
    # Build tools
    ("cargo",),
    ("go",),
    ("mvn",),
    ("gradle",),
    ("make",),
    ("cmake",),
    # Common utilities
    ("curl",),
    ("wget",),
    ("jq",),
    ("xargs",),
]

SHELL_META_CHARS = {"|", "&", ";", ">", "<", "$", "`", "(", ")"}


def _matches_prefix(tokens: list[str], prefixes: list[tuple[str, ...]]) -> bool:
    return any(tokens[: len(prefix)] == list(prefix) for prefix in prefixes)


def _classify_command(command: str) -> tuple[list[str], bool, str]:
    """Return parsed tokens, whether approval is required, and the reason."""
    if any(char in command for char in SHELL_META_CHARS):
        return [], True, "Shell-composed commands require approval."

    try:
        tokens = shlex.split(command)
    except ValueError:
        return [], True, "Command parsing failed and requires approval."

    if not tokens:
        return [], False, ""

    if _matches_prefix(tokens, SAFE_COMMAND_PREFIXES):
        return tokens, False, ""

    return tokens, True, "This command may mutate the repo or invoke external tooling."


def _merge_env(extra_env: dict[str, str] | None) -> dict[str, str]:
    env = dict(os.environ)
    if extra_env:
        env.update({str(key): str(value) for key, value in extra_env.items()})
    return env


def _truncate_output(output: str, max_chars: int) -> str:
    if len(output) <= max_chars:
        return output
    return output[:max_chars] + f"\n... (truncated, {len(output)} total chars)"


@dataclass
class ManagedProcess:
    """Tracked interactive process state."""

    process: asyncio.subprocess.Process
    command: str
    cwd: str
    max_buffer_chars: int
    stdout: str = ""
    stderr: str = ""
    stdout_offset: int = 0
    stderr_offset: int = 0
    stdout_task: asyncio.Task[None] | None = None
    stderr_task: asyncio.Task[None] | None = None

    def append_stdout(self, chunk: str) -> None:
        self.stdout = _trim_buffer(self.stdout + chunk, self.max_buffer_chars, "stdout_offset", self)

    def append_stderr(self, chunk: str) -> None:
        self.stderr = _trim_buffer(self.stderr + chunk, self.max_buffer_chars, "stderr_offset", self)


def _trim_buffer(buffer: str, max_chars: int, offset_attr: str, proc: ManagedProcess) -> str:
    if len(buffer) <= max_chars:
        return buffer

    excess = len(buffer) - max_chars
    current_offset = getattr(proc, offset_attr)
    setattr(proc, offset_attr, max(current_offset - excess, 0))
    return buffer[excess:]


class ProcessManager:
    """Manage interactive subprocesses for the session."""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self._processes: dict[int, ManagedProcess] = {}
        self._next_id = 1

    def _resolve_cwd(self, cwd: str | None) -> Path:
        base = self.project_root if not cwd else Path(cwd)
        if not base.is_absolute():
            base = self.project_root / base
        base = base.resolve()
        try:
            base.relative_to(self.project_root)
        except ValueError:
            raise PermissionError(f"Access denied: {base} is outside project root")
        if not base.exists() or not base.is_dir():
            raise FileNotFoundError(f"Working directory not found: {cwd or '.'}")
        return base

    async def start(
        self,
        command: str,
        cwd: str | None,
        env: dict[str, str] | None,
        max_buffer_chars: int,
    ) -> tuple[int, ManagedProcess]:
        resolved_cwd = self._resolve_cwd(cwd)
        proc = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(resolved_cwd),
            env=_merge_env(env),
        )

        proc_id = self._next_id
        self._next_id += 1

        managed = ManagedProcess(
            process=proc,
            command=command,
            cwd=str(resolved_cwd),
            max_buffer_chars=max_buffer_chars,
        )
        managed.stdout_task = asyncio.create_task(self._pump_stream(proc.stdout, managed.append_stdout))
        managed.stderr_task = asyncio.create_task(self._pump_stream(proc.stderr, managed.append_stderr))
        self._processes[proc_id] = managed
        return proc_id, managed

    async def _pump_stream(self, stream: asyncio.StreamReader | None, sink: Any) -> None:
        if stream is None:
            return
        while True:
            chunk = await stream.read(1024)
            if not chunk:
                break
            sink(chunk.decode("utf-8", errors="replace"))

    def get(self, process_id: int) -> ManagedProcess:
        if process_id not in self._processes:
            raise KeyError(f"Unknown process id: {process_id}")
        return self._processes[process_id]

    async def stop(self, process_id: int, force: bool = False) -> ManagedProcess:
        managed = self.get(process_id)
        if managed.process.returncode is None:
            if force:
                managed.process.kill()
            else:
                managed.process.terminate()
            try:
                await asyncio.wait_for(managed.process.wait(), timeout=2)
            except asyncio.TimeoutError:
                managed.process.kill()
                await managed.process.wait()
        return managed


class ShellTool(BaseTool):
    """Base class for command-executing tools."""

    capabilities: tuple[ToolCapability, ...] = (ToolCapability.SHELL,)
    risk_level = ToolRisk.CONDITIONAL
    scope = ToolScope.SHELL

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()

    def _resolve_cwd(self, cwd: str | None) -> Path:
        candidate = self.project_root if not cwd else Path(cwd)
        if not candidate.is_absolute():
            candidate = self.project_root / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(self.project_root)
        except ValueError:
            raise PermissionError(f"Access denied: {candidate} is outside project root")
        if not candidate.exists() or not candidate.is_dir():
            raise FileNotFoundError(f"Working directory not found: {cwd or '.'}")
        return candidate


class RunCommandTool(ShellTool):
    """Execute a shell command."""

    name = "run_command"
    description = (
        "Execute a shell command and return its output. "
        "Use for running scripts, build tools, and tests."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "cwd": {
                "type": "string",
                "description": "Optional working directory inside the project root.",
            },
            "env": {
                "type": "object",
                "description": "Optional environment variables to inject.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds. Default is 60.",
            },
            "max_output_chars": {
                "type": "integer",
                "description": "Maximum characters of combined stdout/stderr to return.",
            },
        },
        "required": ["command"],
    }

    def requires_approval(
        self, approval_mode: ApprovalMode, **kwargs: Any
    ) -> ApprovalRequest | None:
        if approval_mode in {ApprovalMode.AUTO, ApprovalMode.POWER_USER}:
            return None

        command = str(kwargs.get("command", ""))
        tokens, needs_approval, reason = _classify_command(command)
        if approval_mode == ApprovalMode.STRICT or needs_approval:
            return ApprovalRequest(
                tool_name=self.name,
                reason=reason or "Shell commands require approval in strict mode.",
                summary=command,
                command_prefix=tokens,
            )
        return None

    async def dry_run(self, **kwargs: Any) -> ToolResult:
        command = str(kwargs.get("command", ""))
        _tokens, _needs_approval, reason = _classify_command(command)
        description = reason or "Command is considered read-only/safe under the current policy."
        return ToolResult(output=f"Would run: {command}\n{description}", metadata={"command": command})

    async def execute(self, **kwargs: Any) -> ToolResult:
        command = kwargs.get("command", "")
        cwd = kwargs.get("cwd")
        env = kwargs.get("env")
        timeout = kwargs.get("timeout", 60)
        max_output_chars = kwargs.get("max_output_chars", 10000)

        if not command:
            return ToolResult(success=False, error="No command provided")

        try:
            resolved_cwd = self._resolve_cwd(cwd)
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(resolved_cwd),
                env=_merge_env(env),
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult(
                    success=False,
                    error=f"Command timed out after {timeout}s: {command}",
                )

            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()

            output_parts: list[str] = []
            if stdout_str:
                output_parts.append(f"STDOUT:\n{stdout_str}")
            if stderr_str:
                output_parts.append(f"STDERR:\n{stderr_str}")

            output = "\n\n".join(output_parts) if output_parts else "(no output)"
            output = _truncate_output(output, max_output_chars)

            if proc.returncode:
                return ToolResult(
                    success=False,
                    output=output,
                    error=f"Command exited with code {proc.returncode}",
                )
            return ToolResult(output=output)
        except Exception as e:
            return ToolResult(success=False, error=f"Error running command: {e}")


class StartProcessTool(ShellTool):
    """Start an interactive process that can be controlled later."""

    name = "start_process"
    description = "Start an interactive process and return a process id for later reads/writes."
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to start."},
            "cwd": {"type": "string", "description": "Optional working directory."},
            "env": {"type": "object", "description": "Optional environment variables."},
            "max_buffer_chars": {
                "type": "integer",
                "description": "Maximum stdout/stderr buffer to retain.",
            },
        },
        "required": ["command"],
    }
    capabilities = (ToolCapability.SHELL, ToolCapability.PROCESS)
    risk_level = ToolRisk.APPROVAL_REQUIRED
    mutating = True
    scope = ToolScope.PROCESS

    def __init__(self, project_root: str = ".", process_manager: ProcessManager | None = None):
        super().__init__(project_root)
        self.process_manager = process_manager or ProcessManager(project_root)

    def requires_approval(
        self, approval_mode: ApprovalMode, **kwargs: Any
    ) -> ApprovalRequest | None:
        if approval_mode in {ApprovalMode.AUTO, ApprovalMode.POWER_USER}:
            return None
        command = str(kwargs.get("command", ""))
        tokens, _needs_approval, _reason = _classify_command(command)
        return ApprovalRequest(
            tool_name=self.name,
            reason="Interactive processes always require approval.",
            summary=command,
            command_prefix=tokens,
        )

    async def dry_run(self, **kwargs: Any) -> ToolResult:
        command = str(kwargs.get("command", ""))
        return ToolResult(output=f"Would start an interactive process: {command}", metadata={"command": command})

    async def execute(self, **kwargs: Any) -> ToolResult:
        command = kwargs.get("command", "")
        cwd = kwargs.get("cwd")
        env = kwargs.get("env")
        max_buffer_chars = kwargs.get("max_buffer_chars", 20000)

        if not command:
            return ToolResult(success=False, error="No command provided")

        try:
            process_id, managed = await self.process_manager.start(
                command=command,
                cwd=cwd,
                env=env,
                max_buffer_chars=max_buffer_chars,
            )
            return ToolResult(
                output=(
                    f"Started process {process_id} (pid={managed.process.pid}) in {managed.cwd}\n"
                    f"Command: {command}"
                )
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Error starting process: {e}")


class ReadProcessOutputTool(BaseTool):
    """Read buffered output from a managed process."""

    name = "read_process_output"
    description = "Read buffered stdout/stderr from a managed process."
    parameters_schema = {
        "type": "object",
        "properties": {
            "process_id": {"type": "integer", "description": "Process id returned by start_process."},
            "since_last_read": {
                "type": "boolean",
                "description": "Return only new output since the last read. Default true.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return from each stream.",
            },
        },
        "required": ["process_id"],
    }
    capabilities = (ToolCapability.PROCESS,)
    scope = ToolScope.PROCESS
    cache_ttl_seconds = 0

    def __init__(self, process_manager: ProcessManager):
        self.process_manager = process_manager

    async def execute(self, **kwargs: Any) -> ToolResult:
        process_id: int = kwargs.get("process_id", 0)
        since_last_read = kwargs.get("since_last_read", True)
        max_chars = kwargs.get("max_chars", 4000)

        try:
            managed = self.process_manager.get(process_id)
            if since_last_read:
                stdout = managed.stdout[managed.stdout_offset :]
                stderr = managed.stderr[managed.stderr_offset :]
                managed.stdout_offset = len(managed.stdout)
                managed.stderr_offset = len(managed.stderr)
            else:
                stdout = managed.stdout
                stderr = managed.stderr

            stdout = _truncate_output(stdout, max_chars) if stdout else ""
            stderr = _truncate_output(stderr, max_chars) if stderr else ""
            status = "running" if managed.process.returncode is None else f"exited ({managed.process.returncode})"

            parts = [f"Process {process_id}: {status}"]
            if stdout:
                parts.append(f"STDOUT:\n{stdout}")
            if stderr:
                parts.append(f"STDERR:\n{stderr}")
            return ToolResult(output="\n\n".join(parts))
        except Exception as e:
            return ToolResult(success=False, error=f"Error reading process output: {e}")


class WriteProcessInputTool(BaseTool):
    """Write text to a managed process stdin."""

    name = "write_process_input"
    description = "Write text to a managed process stdin."
    parameters_schema = {
        "type": "object",
        "properties": {
            "process_id": {"type": "integer", "description": "Process id returned by start_process."},
            "text": {"type": "string", "description": "Text to write to stdin."},
            "append_newline": {
                "type": "boolean",
                "description": "Append a newline after the text. Default false.",
            },
        },
        "required": ["process_id", "text"],
    }
    capabilities = (ToolCapability.PROCESS,)
    risk_level = ToolRisk.APPROVAL_REQUIRED
    scope = ToolScope.PROCESS
    mutating = True

    def __init__(self, process_manager: ProcessManager):
        self.process_manager = process_manager

    def requires_approval(
        self, approval_mode: ApprovalMode, **kwargs: Any
    ) -> ApprovalRequest | None:
        if approval_mode in {ApprovalMode.AUTO, ApprovalMode.POWER_USER}:
            return None
        return ApprovalRequest(
            tool_name=self.name,
            reason="Writing to an interactive process always requires approval.",
            summary=f"process {kwargs.get('process_id')}",
        )

    async def dry_run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            output=f"Would write to process {kwargs.get('process_id')}",
            metadata={"process_id": kwargs.get("process_id"), "text_length": len(kwargs.get("text", ""))},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        process_id: int = kwargs.get("process_id", 0)
        text = kwargs.get("text", "")
        append_newline = kwargs.get("append_newline", False)

        try:
            managed = self.process_manager.get(process_id)
            if managed.process.stdin is None:
                return ToolResult(success=False, error="Process stdin is not available")
            payload = text + ("\n" if append_newline else "")
            managed.process.stdin.write(payload.encode("utf-8"))
            await managed.process.stdin.drain()
            return ToolResult(output=f"Wrote {len(payload)} characters to process {process_id}")
        except Exception as e:
            return ToolResult(success=False, error=f"Error writing process input: {e}")


class StopProcessTool(BaseTool):
    """Stop a managed process."""

    name = "stop_process"
    description = "Terminate or kill a managed process."
    parameters_schema = {
        "type": "object",
        "properties": {
            "process_id": {"type": "integer", "description": "Process id returned by start_process."},
            "force": {
                "type": "boolean",
                "description": "Kill the process immediately instead of terminating it.",
            },
        },
        "required": ["process_id"],
    }
    capabilities = (ToolCapability.PROCESS,)
    risk_level = ToolRisk.APPROVAL_REQUIRED
    scope = ToolScope.PROCESS
    mutating = True
    reversible = False

    def __init__(self, process_manager: ProcessManager):
        self.process_manager = process_manager

    def requires_approval(
        self, approval_mode: ApprovalMode, **kwargs: Any
    ) -> ApprovalRequest | None:
        if approval_mode in {ApprovalMode.AUTO, ApprovalMode.POWER_USER}:
            return None
        return ApprovalRequest(
            tool_name=self.name,
            reason="Stopping an interactive process requires approval.",
            summary=f"process {kwargs.get('process_id')}",
        )

    async def dry_run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            output=f"Would stop process {kwargs.get('process_id')}",
            metadata={"process_id": kwargs.get("process_id"), "force": kwargs.get("force", False)},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        process_id: int = kwargs.get("process_id", 0)
        force = kwargs.get("force", False)

        try:
            managed = await self.process_manager.stop(process_id, force=force)
            status = managed.process.returncode
            return ToolResult(output=f"Stopped process {process_id} with exit code {status}")
        except Exception as e:
            return ToolResult(success=False, error=f"Error stopping process: {e}")
