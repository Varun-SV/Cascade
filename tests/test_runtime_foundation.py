"""Tests for runtime models and the event bus."""

from __future__ import annotations

from cascade.core.events import EventBus
from cascade.core.runtime import ExecutionEvent, RetryReflection, WorkingMemory


async def test_event_bus_records_history():
    bus = EventBus()
    received: list[str] = []

    async def subscriber(event: ExecutionEvent) -> None:
        received.append(event.event_type)

    bus.subscribe(subscriber)
    await bus.emit(
        ExecutionEvent(
            event_type="task.started",
            task_id="task-1",
            session_id="session-1",
            message="started",
        )
    )

    assert received == ["task.started"]
    assert len(bus.history) == 1


def test_working_memory_trims_results_and_reflections():
    memory = WorkingMemory(goal="Ship the feature")
    for index in range(12):
        memory.add_tool_result(f"result-{index}", max_items=4)

    for index in range(8):
        memory.add_reflection(
            RetryReflection(
                failure_class="tool_failure",
                explanation=f"reflection-{index}",
                blocker="blocked",
                retry_plan="retry",
            ),
            max_items=3,
        )

    assert memory.recent_tool_results == ["result-8", "result-9", "result-10", "result-11"]
    assert [item.explanation for item in memory.reflections] == [
        "reflection-5",
        "reflection-6",
        "reflection-7",
    ]
