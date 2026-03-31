"""Extension protocols for tools, providers, and planner strategies."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cascade.tools.base import BaseTool


@runtime_checkable
class ToolProtocol(Protocol):
    """Protocol for third-party Cascade tools."""

    name: str

    def build(self, project_root: str) -> BaseTool | list[BaseTool]:
        """Build one or more tool instances for registration."""


@runtime_checkable
class ProviderProtocol(Protocol):
    """Protocol for third-party provider factories."""

    provider_name: str

    def build(self, **kwargs: object) -> object:
        """Build a provider instance."""
