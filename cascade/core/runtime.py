"""Structured runtime models for execution state, planning, and tracing."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventLevel(str, Enum):
    """Severity or importance of an execution event."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ExecutionEvent(BaseModel):
    """A single structured event emitted during task execution."""

    event_type: str
    task_id: str
    session_id: str
    agent_id: str = ""
    parent_agent_id: str = ""
    model_id: str = ""
    subtask_id: str = ""
    level: EventLevel = EventLevel.INFO
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    cost: float = 0.0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class RetryReflection(BaseModel):
    """Captured reasoning after a failed attempt before retrying."""

    failure_class: str
    explanation: str
    evidence: list[str] = Field(default_factory=list)
    blocker: str = ""
    retry_plan: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class WorkingMemory(BaseModel):
    """Scratchpad-like state that survives across retries and tool calls."""

    goal: str
    constraints: list[str] = Field(default_factory=list)
    completed_subgoals: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    confidence_signals: list[str] = Field(default_factory=list)
    recent_tool_results: list[str] = Field(default_factory=list)
    reflections: list[RetryReflection] = Field(default_factory=list)

    def add_tool_result(self, summary: str, max_items: int = 8) -> None:
        self.recent_tool_results.append(summary)
        if len(self.recent_tool_results) > max_items:
            self.recent_tool_results = self.recent_tool_results[-max_items:]

    def add_reflection(self, reflection: RetryReflection, max_items: int = 6) -> None:
        self.reflections.append(reflection)
        if len(self.reflections) > max_items:
            self.reflections = self.reflections[-max_items:]


class DelegationEnvelope(BaseModel):
    """Structured handoff sent from one agent to another."""

    title: str
    goal: str
    constraints: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    expected_output_schema: dict[str, Any] = Field(default_factory=dict)
    budget_ceiling: float | None = None
    context_notes: str = ""
    repo_context: str = ""


class PlanStep(BaseModel):
    """A single high-level step in a dry-run plan preview."""

    title: str
    detail: str
    tools: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class PlanPreview(BaseModel):
    """Additive API result for explain/preflight flows."""

    summary: str
    steps: list[PlanStep] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    estimated_cost: float | None = None
    repo_snapshot: str = ""


class ExecutionContext(BaseModel):
    """Per-task execution context shared across runtime components."""

    task_id: str
    session_id: str
    task_description: str
    project_root: str
    approval_mode: str
    planner_model_id: str
    current_subtask_id: str = ""
    current_agent_id: str = ""
    current_model_id: str = ""
    task_artifact_dir: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def child(self, *, agent_id: str, model_id: str, subtask_id: str = "") -> "ExecutionContext":
        """Create a child-scoped context for a delegated agent."""
        return self.model_copy(
            update={
                "current_agent_id": agent_id,
                "current_model_id": model_id,
                "current_subtask_id": subtask_id,
            }
        )
