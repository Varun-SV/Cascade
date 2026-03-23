"""Ollama local model provider implementation."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

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


class OllamaProvider(BaseProvider):
    """Provider for local Ollama models."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "qwen2.5-coder:7b",
        base_url: str = "http://localhost:11434",
        **kwargs: Any,
    ):
        super().__init__(api_key=api_key, model=model, **kwargs)
        self.base_url = base_url.rstrip("/")

    def _format_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert generic messages to Ollama chat format."""
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                api_messages.append({"role": "system", "content": msg.content})
            elif msg.role == Role.USER:
                api_messages.append({"role": "user", "content": msg.content})
            elif msg.role == Role.ASSISTANT:
                entry: dict[str, Any] = {"role": "assistant", "content": msg.content}
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "function": {
                                "name": tc.name,
                                "arguments": tc.arguments,
                            }
                        }
                        for tc in msg.tool_calls
                    ]
                api_messages.append(entry)
            elif msg.role == Role.TOOL and msg.tool_result:
                api_messages.append(
                    {"role": "tool", "content": msg.tool_result.content}
                )

        return api_messages

    def _format_tools(self, tools: list[ToolSchema]) -> list[dict[str, Any]]:
        """Convert tool schemas to Ollama format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    async def _check_health(self) -> bool:
        """Check if Ollama server is running."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> Response:
        """Generate a completion using Ollama."""
        if not await self._check_health():
            raise RuntimeError(
                f"Ollama server not reachable at {self.base_url}. "
                "Make sure Ollama is running: `ollama serve`"
            )

        api_messages = self._format_messages(messages)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if tools:
            payload["tools"] = self._format_tools(tools)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        # Parse response
        message_data = data.get("message", {})
        content = message_data.get("content", "")
        tool_calls: list[ToolCall] = []

        if message_data.get("tool_calls"):
            for tc in message_data["tool_calls"]:
                func = tc.get("function", {})
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tool_calls.append(
                    ToolCall(
                        id=func.get("name", ""),
                        name=func.get("name", ""),
                        arguments=args,
                    )
                )

        # Estimate token usage from response metadata
        usage = Usage(
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
        )

        return Response(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=self.model,
            stop_reason=data.get("done_reason", ""),
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion from Ollama."""
        if not await self._check_health():
            raise RuntimeError(f"Ollama server not reachable at {self.base_url}")

        api_messages = self._format_messages(messages)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if tools:
            payload["tools"] = self._format_tools(tools)

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg = data.get("message", {})
                    if msg.get("content"):
                        yield StreamChunk(content=msg["content"])

                    if data.get("done"):
                        yield StreamChunk(
                            is_final=True,
                            usage=Usage(
                                input_tokens=data.get("prompt_eval_count", 0),
                                output_tokens=data.get("eval_count", 0),
                            ),
                        )

    def get_cost(self, usage: Usage) -> float:
        """Local models are free."""
        return 0.0

    def supports_tools(self) -> bool:
        """Ollama supports tools for compatible models."""
        return True

    async def list_models(self) -> list[str]:
        """List locally available Ollama models."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    return [m["name"] for m in data.get("models", [])]
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        return []
