"""Task and subtask data models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Status of a task or subtask."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"





class SubTask(BaseModel):
    """A decomposed unit of work."""

    id: str = ""
    description: str
    assigned_model: str = ""
    assigned_tools: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = Field(default_factory=list)  # IDs of prerequisite subtasks
    result: str = ""
    error: str = ""
    confidence_score: float = 1.0
    tool_calls_made: int = 0
    retries: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def mark_in_progress(self) -> None:
        self.status = TaskStatus.IN_PROGRESS

    def mark_completed(self, result: str) -> None:
        self.status = TaskStatus.COMPLETED
        self.result = result

    def mark_failed(self, error: str) -> None:
        self.status = TaskStatus.FAILED
        self.error = error

    def mark_escalated(self, reason: str) -> None:
        self.status = TaskStatus.ESCALATED
        self.error = reason


class TaskPlan(BaseModel):
    """A plan of decomposed subtasks for executing a user request."""

    subtasks: list[SubTask] = Field(default_factory=list)
    summary: str = ""
    reasoning: str = ""

    def get_next_subtask(self) -> SubTask | None:
        """Get the next subtask that is ready to execute (all dependencies met)."""
        completed_ids = {
            st.id for st in self.subtasks if st.status == TaskStatus.COMPLETED
        }

        for st in self.subtasks:
            if st.status == TaskStatus.PENDING:
                if all(dep in completed_ids for dep in st.dependencies):
                    return st
        return None

    def is_complete(self) -> bool:
        """Check if all subtasks are completed."""
        return all(
            st.status in (TaskStatus.COMPLETED, TaskStatus.ESCALATED)
            for st in self.subtasks
        )

    def has_failures(self) -> bool:
        """Check if any subtasks failed."""
        return any(st.status == TaskStatus.FAILED for st in self.subtasks)


class Task(BaseModel):
    """Top-level user request."""

    id: str = ""
    description: str
    plan: Optional[TaskPlan] = None
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    total_cost: float = 0.0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class TaskResult(BaseModel):
    """Final result of a completed task."""

    success: bool = True
    summary: str = ""
    details: str = ""
    subtask_results: list[dict[str, Any]] = Field(default_factory=list)
    total_cost: float = 0.0
    model_costs: dict[str, float] = Field(default_factory=dict)
