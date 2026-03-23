"""Abstract tool base class and tool registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from cascade.providers.base import ToolSchema


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

    def get_tools(self, allowed_names: list[str]) -> list[BaseTool]:
        """Return all tools that match the allowed names. Use ['all'] for everything."""
        if allowed_names == ["all"]:
            return list(self._tools.values())
        return [t for k, t in self._tools.items() if k in allowed_names]

    def get_schemas(self, allowed_names: list[str]) -> list[ToolSchema]:
        """Return tool schemas for the allowed tool names."""
        return [t.to_schema() for t in self.get_tools(allowed_names)]

    def list_all(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    async def execute(self, name: str, allowed_names: list[str], **kwargs: Any) -> ToolResult:
        """Execute a tool by name, checking if it is in the allowed list."""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(success=False, error=f"Unknown tool: {name}")
            
        if allowed_names != ["all"] and name not in allowed_names:
            return ToolResult(
                success=False,
                error=f"Tool '{name}' is not permitted for this agent. Allowed tools: {', '.join(allowed_names)}",
            )
            
        try:
            return await tool.execute(**kwargs)
        except Exception as e:
            return ToolResult(success=False, error=f"Tool execution error: {str(e)}")
