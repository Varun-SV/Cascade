"""Abstract tool base class, manifests, and registry/runtime helpers."""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from cascade.core.approval import (
    ApprovalHandler,
    ApprovalMode,
    ApprovalRequest,
    command_prefix_matches,
    resolve_approval,
)
from cascade.core.events import EventBus
from cascade.core.runtime import EventLevel, ExecutionContext, ExecutionEvent
from cascade.observability.rollback import RollbackManager
from cascade.providers.base import ToolSchema


class ToolResult(BaseModel):
    """Result of a tool execution or dry-run preview."""

    success: bool = True
    output: str = ""
    error: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class ToolScope(str, Enum):
    """Primary scope touched by a tool."""

    FILE = "file"
    SHELL = "shell"
    PROCESS = "process"
    GIT = "git"
    NETWORK = "network"
    META = "meta"


class ApprovalClass(str, Enum):
    """Approval classification for a tool."""

    SAFE = "safe"
    GUARDED = "guarded"
    STRICT = "strict"


class ToolManifest(BaseModel):
    """Declarative tool manifest used for planning, safety, and caching."""

    name: str
    scope: ToolScope
    capabilities: list[ToolCapability] = Field(default_factory=list)
    mutating: bool = False
    reversible: bool = True
    cache_ttl_seconds: int = 0
    dry_run_supported: bool = False
    approval_class: ApprovalClass = ApprovalClass.SAFE


class BaseTool(ABC):
    """Abstract base for all tools."""

    name: str = ""
    description: str = ""
    parameters_schema: dict[str, Any] = {}
    capabilities: tuple[ToolCapability, ...] = ()
    risk_level: ToolRisk = ToolRisk.SAFE
    scope: ToolScope = ToolScope.META
    mutating: bool = False
    reversible: bool = True
    cache_ttl_seconds: int = 0

    @property
    def manifest(self) -> ToolManifest:
        """Build a tool manifest from class attributes."""
        approval_class = ApprovalClass.SAFE
        if self.risk_level == ToolRisk.CONDITIONAL:
            approval_class = ApprovalClass.GUARDED
        elif self.risk_level == ToolRisk.APPROVAL_REQUIRED:
            approval_class = ApprovalClass.STRICT

        return ToolManifest(
            name=self.name,
            scope=self.scope,
            capabilities=list(self.capabilities),
            mutating=self.mutating,
            reversible=self.reversible,
            cache_ttl_seconds=self.cache_ttl_seconds,
            dry_run_supported=self.mutating,
            approval_class=approval_class,
        )

    def to_schema(self) -> ToolSchema:
        """Convert to a ToolSchema for the LLM."""
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters=self.parameters_schema,
        )

    async def dry_run(self, **kwargs: Any) -> ToolResult:
        """Describe what the tool would do without mutating state."""
        summary = kwargs.get("path") or kwargs.get("command") or self.name
        return ToolResult(
            output=f"Dry run: {self.name} would run with target {summary}",
            metadata={"arguments": {k: v for k, v in kwargs.items() if k not in {'content', 'patch'}}},
        )

    def requires_approval(
        self, approval_mode: ApprovalMode, **kwargs: Any
    ) -> ApprovalRequest | None:
        """Return an approval request when the tool should pause for confirmation."""
        if approval_mode in {ApprovalMode.AUTO, ApprovalMode.POWER_USER}:
            return None

        if approval_mode == ApprovalMode.STRICT:
            return self._build_default_approval_request(**kwargs)

        if self.risk_level == ToolRisk.APPROVAL_REQUIRED:
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


class ToolRegistry:
    """Discovers, registers, and manages tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._cache: dict[str, tuple[float, ToolResult]] = {}

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
        return [tool for key, tool in self._tools.items() if key in allowed_names]

    def get_schemas(self, allowed_names: list[str]) -> list[ToolSchema]:
        """Return tool schemas for the allowed tool names."""
        return [tool.to_schema() for tool in self.get_tools(allowed_names)]

    def get_capability_graph(self, allowed_names: list[str] | None = None) -> dict[str, dict[str, Any]]:
        """Return manifests keyed by tool name for planning and inspection."""
        tools = self._tools.values() if allowed_names is None else self.get_tools(allowed_names)
        return {tool.name: tool.manifest.model_dump() for tool in tools}

    def list_all(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def _cache_key(self, name: str, kwargs: dict[str, Any]) -> str:
        return json.dumps({"name": name, "kwargs": kwargs}, sort_keys=True, default=str)

    def _load_cached(self, key: str, ttl: int) -> ToolResult | None:
        if ttl <= 0:
            return None
        if key not in self._cache:
            return None
        created_at, result = self._cache[key]
        if (time.time() - created_at) > ttl:
            self._cache.pop(key, None)
            return None
        return result

    def _store_cached(self, key: str, ttl: int, result: ToolResult) -> None:
        if ttl > 0 and result.success:
            self._cache[key] = (time.time(), result)

    def _invalidate_cache(self) -> None:
        self._cache.clear()

    async def _emit(
        self,
        *,
        event_bus: EventBus | None,
        execution_context: ExecutionContext | None,
        event_type: str,
        message: str,
        tool_name: str,
        payload: dict[str, Any] | None = None,
        level: EventLevel = EventLevel.INFO,
    ) -> None:
        if not event_bus or not execution_context:
            return
        await event_bus.emit(
            ExecutionEvent(
                event_type=event_type,
                task_id=execution_context.task_id,
                session_id=execution_context.session_id,
                agent_id=execution_context.current_agent_id,
                model_id=execution_context.current_model_id,
                subtask_id=execution_context.current_subtask_id,
                level=level,
                message=message,
                payload={"tool_name": tool_name, **(payload or {})},
            )
        )

    async def execute(self, name: str, allowed_names: list[str], **kwargs: Any) -> ToolResult:
        """Execute a tool by name, checking permissions, dry-run, cache, and approval."""
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
        approval_handler: ApprovalHandler | None = kwargs.pop("approval_handler", None)
        allowed_prefixes = kwargs.pop("allowed_command_prefixes", None)
        dry_run_requested = bool(kwargs.pop("dry_run", False))
        event_bus: EventBus | None = kwargs.pop("event_bus", None)
        execution_context: ExecutionContext | None = kwargs.pop("execution_context", None)
        rollback_manager: RollbackManager | None = kwargs.pop("rollback_manager", None)

        manifest = tool.manifest
        cache_key = self._cache_key(name, kwargs)

        if not manifest.mutating:
            cached = self._load_cached(cache_key, manifest.cache_ttl_seconds)
            if cached:
                await self._emit(
                    event_bus=event_bus,
                    execution_context=execution_context,
                    event_type="tool.cache.hit",
                    message=f"Served cached result for {name}.",
                    tool_name=name,
                )
                return cached

        approval_request = tool.requires_approval(approval_mode=approval_mode, **kwargs)
        if approval_request:
            dry_run_preview = await tool.dry_run(**kwargs)
            approval_request.summary = dry_run_preview.output or approval_request.summary
            approval_request.details = {**approval_request.details, **dry_run_preview.metadata}
            await self._emit(
                event_bus=event_bus,
                execution_context=execution_context,
                event_type="approval.requested",
                message=f"Approval required for {name}.",
                tool_name=name,
                payload={"summary": approval_request.summary},
                level=EventLevel.WARNING,
            )
            if not command_prefix_matches(approval_request.command_prefix, allowed_prefixes):
                decision = await resolve_approval(approval_request, approval_handler)
                await self._emit(
                    event_bus=event_bus,
                    execution_context=execution_context,
                    event_type="approval.decision",
                    message="Approval granted." if decision.approved else "Approval denied.",
                    tool_name=name,
                    payload={"reason": decision.reason},
                    level=EventLevel.INFO if decision.approved else EventLevel.WARNING,
                )
                if not decision.approved:
                    reason = decision.reason or approval_request.reason
                    return ToolResult(
                        success=False,
                        error=f"Approval denied for tool '{name}': {reason}",
                    )

        if dry_run_requested:
            result = await tool.dry_run(**kwargs)
            await self._emit(
                event_bus=event_bus,
                execution_context=execution_context,
                event_type="tool.dry_run",
                message=f"Dry run completed for {name}.",
                tool_name=name,
                payload=result.metadata,
            )
            return result

        if manifest.mutating:
            self._invalidate_cache()
            if rollback_manager is not None and execution_context is not None:
                await rollback_manager.capture_before(tool_name=name, kwargs=kwargs, execution_context=execution_context)

        await self._emit(
            event_bus=event_bus,
            execution_context=execution_context,
            event_type="tool.call",
            message=f"Executing tool {name}.",
            tool_name=name,
        )

        try:
            result = await tool.execute(**kwargs)
        except Exception as error:  # pragma: no cover - defensive
            result = ToolResult(success=False, error=f"Tool execution error: {error}")

        if manifest.mutating and rollback_manager is not None and execution_context is not None:
            await rollback_manager.capture_after(
                tool_name=name,
                kwargs=kwargs,
                execution_context=execution_context,
                result=result,
            )

        if result.success and not manifest.mutating:
            self._store_cached(cache_key, manifest.cache_ttl_seconds, result)

        await self._emit(
            event_bus=event_bus,
            execution_context=execution_context,
            event_type="tool.result",
            message=f"Tool {name} {'succeeded' if result.success else 'failed'}.",
            tool_name=name,
            payload={"success": result.success, "error": result.error, **result.metadata},
            level=EventLevel.INFO if result.success else EventLevel.ERROR,
        )

        return result
