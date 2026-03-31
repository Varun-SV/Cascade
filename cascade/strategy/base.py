"""Planner strategy protocol for swappable orchestration approaches."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from cascade.core.runtime import PlanPreview
from cascade.core.task import TaskResult

if TYPE_CHECKING:
    from cascade.api import Cascade


class PlannerStrategy(ABC):
    """Strategy interface for planning and executing user tasks."""

    @abstractmethod
    async def execute(self, cascade: "Cascade", task_description: str) -> TaskResult:
        """Run a task through the strategy."""

    @abstractmethod
    async def explain(self, cascade: "Cascade", task_description: str) -> PlanPreview:
        """Produce a dry-run plan preview."""
