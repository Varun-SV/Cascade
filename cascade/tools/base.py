"""Abstract tool base class and tool registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from cascade.core.approval import (
    ApprovalHandler,
    ApprovalMode,
    ApprovalRequest,
    command_prefix_matches,
    resolve_approval,
)
from pydantic import BaseModel

from cascade.providers.base import ToolSchema


class ToolResult(BaseModel):
    """Result of a tool execution."""

    success: bool = True
    output: str = ""
    error: str = ""


class ToolCapability(str, Enum):
    """Broad tool capability categories."""

    READ = "read"
    WRITE = "write"
    SHELL = "shell"
    PROCESS = "process"
    GIT = "git"
    NETWORK = "network"


class ToolRisk(str, Enum):
    """Risk hints used by the approval layer."""

    SAFE = "safe"
    CONDITIONAL = "conditional"
    APPROVAL_REQUIRED = "approval_required"


class BaseTool(ABC):
    """Abstract base for all tools."""

    name: str = ""
    description: str = ""
    parameters_schema: dict[str, Any] = {}
    capabilities: tuple[ToolCapability, ...] = ()
    risk_level: ToolRisk = ToolRisk.SAFE

    def to_schema(self) -> ToolSchema:
        """Convert to a ToolSchema for the LLM."""
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters=self.parameters_schema,
        )

    def requires_approval(
        self, approval_mode: ApprovalMode, **kwargs: Any
    ) -> ApprovalRequest | None:
        """Return an approval request when the tool should pause for confirmation."""
        if approval_mode == ApprovalMode.POWER_USER:
            return None

        if self.risk_level == ToolRisk.APPROVAL_REQUIRED:
            return self._build_default_approval_request(**kwargs)

        if approval_mode == ApprovalMode.STRICT and any(
            cap in self.capabilities
            for cap in (
                ToolCapability.WRITE,
                ToolCapability.SHELL,
                ToolCapability.PROCESS,
                ToolCapability.GIT,
                ToolCapability.NETWORK,
            )
        ):
            return self._build_default_approval_request(**kwargs)

        return None

    def _build_default_approval_request(self, **kwargs: Any) -> ApprovalRequest:
        """Create a generic approval request from tool arguments."""
        summary = kwargs.get("path") or kwargs.get("command") or self.name
        return ApprovalRequest(
            tool_name=self.name,
            reason=f"Tool '{self.name}' requires approval before it can run.",
            summary=str(summary),
            details={k: v for k, v in kwargs.items() if k not in {"content", "replacement", "patch"}},
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

        approval_mode = kwargs.pop("approval_mode", ApprovalMode.GUARDED)
        if not isinstance(approval_mode, ApprovalMode):
            approval_mode = ApprovalMode(str(approval_mode))
        approval_handler = kwargs.pop("approval_handler", None)
        allowed_prefixes = kwargs.pop("allowed_command_prefixes", None)

        approval_request = tool.requires_approval(approval_mode=approval_mode, **kwargs)
        if approval_request:
            if not command_prefix_matches(approval_request.command_prefix, allowed_prefixes):
                decision = await resolve_approval(approval_request, approval_handler)
                if not decision.approved:
                    reason = decision.reason or approval_request.reason
                    return ToolResult(
                        success=False,
                        error=f"Approval denied for tool '{name}': {reason}",
                    )

        try:
            return await tool.execute(**kwargs)
        except Exception as e:
            return ToolResult(success=False, error=f"Tool execution error: {str(e)}")
