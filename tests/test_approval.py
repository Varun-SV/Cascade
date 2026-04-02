"""Tests for guarded approval flow."""

from __future__ import annotations

import pytest

from cascade.core.approval import ApprovalMode
from cascade.tools.base import ToolRegistry
from cascade.tools.file_ops import WriteFileTool
from cascade.tools.shell import RunCommandTool


@pytest.mark.asyncio
async def test_safe_command_runs_without_approval(tmp_path):
    registry = ToolRegistry()
    registry.register(RunCommandTool(str(tmp_path)))

    result = await registry.execute(
        "run_command",
        allowed_names=["all"],
        command="pwd",
        approval_mode=ApprovalMode.GUARDED,
    )

    assert result.success


@pytest.mark.asyncio
async def test_risky_command_uses_callback(tmp_path):
    registry = ToolRegistry()
    registry.register(RunCommandTool(str(tmp_path)))
    requests = []

    async def approve(request):
        requests.append(request)
        return True

    result = await registry.execute(
        "run_command",
        allowed_names=["all"],
        command="printf hello",
        approval_mode=ApprovalMode.GUARDED,
        approval_handler=approve,
    )

    assert result.success
    assert len(requests) == 1
    assert requests[0].tool_name == "run_command"


@pytest.mark.asyncio
async def test_risky_command_fails_closed_without_approval(tmp_path):
    registry = ToolRegistry()
    registry.register(RunCommandTool(str(tmp_path)))

    result = await registry.execute(
        "run_command",
        allowed_names=["all"],
        command="printf hello",
        approval_mode=ApprovalMode.GUARDED,
    )

    assert not result.success
    assert "approval denied" in result.error.lower()


@pytest.mark.asyncio
async def test_allowlisted_command_prefix_bypasses_prompt(tmp_path):
    registry = ToolRegistry()
    registry.register(RunCommandTool(str(tmp_path)))
    called = False

    async def approve(_request):
        nonlocal called
        called = True
        return False

    result = await registry.execute(
        "run_command",
        allowed_names=["all"],
        command="printf hello",
        approval_mode=ApprovalMode.GUARDED,
        approval_handler=approve,
        allowed_command_prefixes=[["printf"]],
    )

    assert result.success
    assert called is False


@pytest.mark.asyncio
async def test_repo_mutating_file_tool_requires_approval(tmp_path):
    registry = ToolRegistry()
    registry.register(WriteFileTool(str(tmp_path)))

    # In GUARDED mode, write_file should auto-execute (no approval needed)
    result = await registry.execute(
        "write_file",
        allowed_names=["all"],
        path="hello.txt",
        content="hi",
        approval_mode=ApprovalMode.GUARDED,
    )
    assert result.success

    # In STRICT mode, write_file should still require approval
    result = await registry.execute(
        "write_file",
        allowed_names=["all"],
        path="hello2.txt",
        content="hi",
        approval_mode=ApprovalMode.STRICT,
    )
    assert not result.success
    assert "approval denied" in result.error.lower()
