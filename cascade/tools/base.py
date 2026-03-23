"""Abstract tool base class and tool registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from cascade.providers.base import ToolSchema


class Tier(str, Enum):
    """Agent tiers."""

    T1 = "t1"
    T2 = "t2"
    T3 = "t3"


class ToolResult(BaseModel):
    """Result of a tool execution."""

    success: bool = True
    output: str = ""
    error: str = ""


class BaseTool(ABC):
    """Abstract base for all tools."""

    name: str = ""
    description: str = ""
    parameters_schema: dict[str, Any] = {}
    allowed_tiers: set[Tier] = {Tier.T1, Tier.T2, Tier.T3}

    def is_allowed_for(self, tier: Tier) -> bool:
        """Check if this tool is accessible for a given tier."""
        return tier in self.allowed_tiers

    def to_schema(self) -> ToolSchema:
        """Convert to a ToolSchema for the LLM."""
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters=self.parameters_schema,
        )

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given arguments."""
        ...


class ToolRegistry:
    """Discovers, registers, and manages tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_tools_for_tier(self, tier: Tier) -> list[BaseTool]:
        """Return all tools accessible to a given tier."""
        return [t for t in self._tools.values() if t.is_allowed_for(tier)]

    def get_schemas_for_tier(self, tier: Tier) -> list[ToolSchema]:
        """Return tool schemas for a given tier."""
        return [t.to_schema() for t in self.get_tools_for_tier(tier)]

    def list_all(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    async def execute(self, name: str, tier: Tier, **kwargs: Any) -> ToolResult:
        """Execute a tool by name, checking tier permissions."""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(success=False, error=f"Unknown tool: {name}")
        if not tool.is_allowed_for(tier):
            return ToolResult(
                success=False,
                error=f"Tool '{name}' is not allowed for tier {tier.value}",
            )
        try:
            return await tool.execute(**kwargs)
        except Exception as e:
            return ToolResult(success=False, error=f"Tool execution error: {str(e)}")
