"""Tests for shell and process tools."""

from __future__ import annotations

import asyncio
import shlex
import sys

import pytest

from cascade.tools.shell import (
    ProcessManager,
    ReadProcessOutputTool,
    RunCommandTool,
    StartProcessTool,
    StopProcessTool,
    WriteProcessInputTool,
)


@pytest.mark.asyncio
async def test_run_command_supports_cwd_and_env(tmp_path):
    (tmp_path / "subdir").mkdir()
    tool = RunCommandTool(str(tmp_path))
    command = (
        f"{shlex.quote(sys.executable)} -c "
        "\"import os; print(os.getenv('CASCADE_TEST')); print(os.getcwd())\""
    )

    result = await tool.execute(
        command=command,
        cwd="subdir",
        env={"CASCADE_TEST": "yes"},
    )

    assert result.success
    assert "yes" in result.output
    assert str(tmp_path / "subdir") in result.output


@pytest.mark.asyncio
async def test_interactive_process_lifecycle(tmp_path):
    manager = ProcessManager(str(tmp_path))
    start = StartProcessTool(str(tmp_path), manager)
    read = ReadProcessOutputTool(manager)
    write = WriteProcessInputTool(manager)
    stop = StopProcessTool(manager)

    command = (
        f"{shlex.quote(sys.executable)} -u -c "
        "\"print('ready', flush=True); value = input(); print(value.upper(), flush=True)\""
    )

    start_result = await start.execute(command=command)
    assert start_result.success
    assert "Started process 1" in start_result.output

    await asyncio.sleep(0.2)
    initial = await read.execute(process_id=1)
    assert initial.success
    assert "ready" in initial.output

    write_result = await write.execute(process_id=1, text="hello", append_newline=True)
    assert write_result.success

    await asyncio.sleep(0.2)
    follow_up = await read.execute(process_id=1)
    assert follow_up.success
    assert "HELLO" in follow_up.output

    stop_result = await stop.execute(process_id=1)
    assert stop_result.success
    assert "exit code 0" in stop_result.output
