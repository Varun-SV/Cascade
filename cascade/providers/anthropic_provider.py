"""Anthropic (Claude) provider implementation."""

from __future__ import annotations

from typing import Any, AsyncIterator

import anthropic

from cascade.providers.base import (
    BaseProvider,
    Message,
    Response,
    Role,
    StreamChunk,
    ToolCall,
    ToolSchema,
    Usage,
)

# Pricing per million tokens (approximate, update as needed)
PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    "claude-haiku-3-20250722": {"input": 0.25, "output": 1.25},
}


class AnthropicProvider(BaseProvider):
    """Provider for Anthropic Claude models."""

    def __init__(self, api_key: str = "", model: str = "claude-sonnet-4-20250514", **kwargs: Any):
        super().__init__(api_key=api_key, model=model, **kwargs)
        self.client = anthropic.AsyncAnthropic(api_key=api_key) if api_key else None

    def _format_messages(
        self, messages: list[Message]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Convert generic messages to Anthropic format. Returns (system_prompt, messages)."""
        system_prompt = ""
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                system_prompt = msg.content
            elif msg.role == Role.USER:
                api_messages.append({"role": "user", "content": msg.content})
            elif msg.role == Role.ASSISTANT:
                if msg.tool_calls:
                    content: list[dict[str, Any]] = []
                    if msg.content:
                        content.append({"type": "text", "text": msg.content})
                    for tc in msg.tool_calls:
                        content.append(
                            {
                                "type": "tool_use",
                                "id": tc.id,
                                "name": tc.name,
                                "input": tc.arguments,
                            }
                        )
                    api_messages.append({"role": "assistant", "content": content})
                else:
                    api_messages.append({"role": "assistant", "content": msg.content})
            elif msg.role == Role.TOOL and msg.tool_result:
                api_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_result.tool_call_id,
                                "content": msg.tool_result.content,
                                "is_error": msg.tool_result.is_error,
                            }
                        ],
                    }
                )

        return system_prompt, api_messages

    def _format_tools(self, tools: list[ToolSchema]) -> list[dict[str, Any]]:
        """Convert generic tool schemas to Anthropic format."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

    def _parse_response(self, raw: Any) -> Response:
        """Parse Anthropic API response into generic Response."""
        content = ""
        tool_calls: list[ToolCall] = []

        for block in raw.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                    )
                )

        return Response(
            content=content,
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=raw.usage.input_tokens,
                output_tokens=raw.usage.output_tokens,
            ),
            model=raw.model,
            stop_reason=raw.stop_reason,
        )

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Response:
        """Generate a completion using Claude."""
        if not self.client:
            raise RuntimeError("Anthropic API key not configured")

        system_prompt, api_messages = self._format_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = self._format_tools(tools)

        raw = await self.client.messages.create(**kwargs)
        return self._parse_response(raw)

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion from Claude."""
        if not self.client:
            raise RuntimeError("Anthropic API key not configured")

        system_prompt, api_messages = self._format_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = self._format_tools(tools)

        async with self.client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if hasattr(event, "type"):
                    if event.type == "content_block_delta":
                        if hasattr(event.delta, "text"):
                            yield StreamChunk(content=event.delta.text)
                    elif event.type == "message_stop":
                        final_message = await stream.get_final_message()
                        yield StreamChunk(
                            is_final=True,
                            usage=Usage(
                                input_tokens=final_message.usage.input_tokens,
                                output_tokens=final_message.usage.output_tokens,
                            ),
                        )

    def get_cost(self, usage: Usage) -> float:
        """Calculate cost based on Claude pricing."""
        pricing = PRICING.get(self.model, {"input": 3.0, "output": 15.0})
        input_cost = (usage.input_tokens / 1_000_000) * pricing["input"]
        output_cost = (usage.output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    async def list_models(self) -> list[str]:
        """List available Claude models."""
        return list(PRICING.keys())
