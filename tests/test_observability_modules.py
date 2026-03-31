"""Tests for trace writing, journaling, and rollback support."""

from __future__ import annotations

import json

from cascade.core.runtime import ExecutionContext, ExecutionEvent
from cascade.observability.journal import ActionJournal
from cascade.observability.rollback import RollbackManager
from cascade.observability.tracing import TaskTraceWriter, load_trace, render_trace_tree
from cascade.tools.base import ToolResult


async def test_trace_writer_persists_and_renders(tmp_path):
    writer = TaskTraceWriter(str(tmp_path), "task-123")
    await writer(
        ExecutionEvent(
            event_type="task.started",
            task_id="task-123",
            session_id="session-1",
            agent_id="planner:1",
            model_id="planner",
            message="Task started",
        )
    )
    trace = writer.finalize()

    loaded = load_trace("task-123", str(tmp_path))
    rendered = render_trace_tree(loaded)

    assert trace["event_count"] == 1
    assert loaded["task_id"] == "task-123"
    assert "Task started" in rendered


async def test_action_journal_writes_hashes(tmp_path):
    journal = ActionJournal(str(tmp_path / "journal.log"))
    await journal(
        ExecutionEvent(
            event_type="tool.result",
            task_id="task-123",
            session_id="session-1",
            agent_id="planner:1",
            model_id="planner",
            message="Tool succeeded",
            payload={"tool_name": "read_file"},
        )
    )
    contents = (tmp_path / "journal.log").read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(contents[0])
    assert payload["payload"]["tool_name"] == "read_file"
    assert payload["result_hash"]


async def test_rollback_manager_restores_snapshot(tmp_path):
    file_path = tmp_path / "sample.py"
    file_path.write_text("print('before')\n", encoding="utf-8")
    manager = RollbackManager(str(tmp_path))
    context = ExecutionContext(
        task_id="task-rollback",
        session_id="session-1",
        task_description="edit sample.py",
        project_root=str(tmp_path),
        approval_mode="guarded",
        planner_model_id="planner",
        task_artifact_dir=str(tmp_path / "artifacts" / "task-rollback"),
    )

    await manager.capture_before(
        tool_name="write_file",
        kwargs={"path": "sample.py"},
        execution_context=context,
    )
    file_path.write_text("print('after')\n", encoding="utf-8")
    await manager.capture_after(
        tool_name="write_file",
        kwargs={"path": "sample.py"},
        execution_context=context,
        result=ToolResult(success=True, output="updated"),
    )

    restored = manager.restore(context.task_artifact_dir)
    assert restored == ["sample.py"]
    assert file_path.read_text(encoding="utf-8") == "print('before')\n"
