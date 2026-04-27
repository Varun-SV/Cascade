"""Abstract base provider and shared data models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, AsyncIterator, Optional

from pydantic import BaseModel, Field


# ── Message Models ──────────────────────────────────────────────────


class Role(str, Enum):
    """Message roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(BaseModel):
    """A tool call made by the model."""

    id: str = ""
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Result of a tool execution."""

    tool_call_id: str = ""
    name: str
    content: str
    is_error: bool = False


class Message(BaseModel):
    """A conversation message."""

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_result: Optional[ToolResult] = None


# ── Response Models ─────────────────────────────────────────────────


class Usage(BaseModel):
    """Token usage statistics."""

    input_tokens: int = 0
    output_tokens: int = 0


class Response(BaseModel):
    """LLM response."""

    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    model: str = ""
    stop_reason: str = ""


class StreamChunk(BaseModel):
    """A chunk from a streaming response."""

    content: str = ""
    tool_call: Optional[ToolCall] = None
    is_final: bool = False
    usage: Optional[Usage] = None


# ── Tool Schema ─────────────────────────────────────────────────────


class ToolSchema(BaseModel):
    """Schema for describing a tool to the LLM."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


# ── Base Provider ───────────────────────────────────────────────────


class BaseProvider(ABC):
    """Abstract LLM provider interface."""

    def __init__(self, api_key: str = "", model: str = "", **kwargs: Any):
        self.api_key = api_key
        self.model = model
        self._last_usage: Usage | None = None

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Response:
        """Generate a completion."""
        ...

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion."""
        ...

    def get_cost(self, usage: Usage) -> float:
        """Calculate cost for token usage. Override per provider."""
        return 0.0

    def supports_tools(self) -> bool:
        """Whether this provider supports native tool calling."""
        return True

    @abstractmethod
    async def list_models(self) -> list[str]:
        """List available models."""
        ...
