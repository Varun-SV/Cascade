"""Shell command execution tool."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from cascade.tools.base import BaseTool, Tier, ToolResult


class RunCommandTool(BaseTool):
    """Execute a shell command."""

    name = "run_command"
    description = (
        "Execute a shell command and return its output. "
        "Use for running scripts, build tools, tests, etc. "
        "Commands run in the project root directory."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds. Default is 60.",
            },
        },
        "required": ["command"],
    }
    allowed_tiers = {Tier.T1, Tier.T2}  # T3 cannot run arbitrary commands

    def __init__(self, project_root: str = "."):
        self.project_root = project_root

    async def execute(self, **kwargs: Any) -> ToolResult:
        command = kwargs.get("command", "")
        timeout = kwargs.get("timeout", 60)

        if not command:
            return ToolResult(success=False, error="No command provided")

        try:
            # Use shell=True for cross-platform compatibility
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.project_root,
                env={**os.environ},
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult(
                    success=False,
                    error=f"Command timed out after {timeout}s: {command}",
                )

            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()

            # Truncate long outputs
            max_len = 10000
            if len(stdout_str) > max_len:
                stdout_str = stdout_str[:max_len] + f"\n... (truncated, {len(stdout_str)} total chars)"
            if len(stderr_str) > max_len:
                stderr_str = stderr_str[:max_len] + f"\n... (truncated, {len(stderr_str)} total chars)"

            output_parts: list[str] = []
            if stdout_str:
                output_parts.append(f"STDOUT:\n{stdout_str}")
            if stderr_str:
                output_parts.append(f"STDERR:\n{stderr_str}")

            output = "\n\n".join(output_parts) if output_parts else "(no output)"
            exit_code = proc.returncode or 0

            if exit_code != 0:
                return ToolResult(
                    success=False,
                    output=output,
                    error=f"Command exited with code {exit_code}",
                )

            return ToolResult(output=output)

        except Exception as e:
            return ToolResult(success=False, error=f"Error running command: {e}")
