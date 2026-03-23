"""OpenAI (GPT) provider implementation."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import openai

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
    "gpt-4o": {"input": 2.50, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    "o1": {"input": 15.0, "output": 60.0},
    "o1-mini": {"input": 3.0, "output": 12.0},
    "o3": {"input": 10.0, "output": 40.0},
    "o3-mini": {"input": 1.10, "output": 4.40},
    "o4-mini": {"input": 1.10, "output": 4.40},
}

# Models that require max_completion_tokens instead of max_tokens
# and don't support the temperature parameter
_REASONING_MODEL_PREFIXES = ("o1", "o3", "o4")


class OpenAIProvider(BaseProvider):
    """Provider for OpenAI GPT models."""

    def __init__(self, api_key: str = "", model: str = "gpt-4o", **kwargs: Any):
        super().__init__(api_key=api_key, model=model, **kwargs)
        self.client = openai.AsyncOpenAI(api_key=api_key) if api_key else None

    def _is_reasoning_model(self) -> bool:
        """Check if the current model is a reasoning model (o1/o3/o4 series)."""
        return self.model.startswith(_REASONING_MODEL_PREFIXES)

    def _build_token_params(self, temperature: float, max_tokens: int) -> dict[str, Any]:
        """Build the correct token/temperature params based on model type.
        
        OpenAI now uses max_completion_tokens as the standard parameter.
        Reasoning models (o-series) additionally don't support temperature.
        """
        params: dict[str, Any] = {
            "max_completion_tokens": max_tokens,
        }
        if not self._is_reasoning_model():
            params["temperature"] = temperature
        return params

    def _format_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert generic messages to OpenAI format."""
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                api_messages.append({"role": "system", "content": msg.content})
            elif msg.role == Role.USER:
                api_messages.append({"role": "user", "content": msg.content})
            elif msg.role == Role.ASSISTANT:
                entry: dict[str, Any] = {"role": "assistant"}
                if msg.content:
                    entry["content"] = msg.content
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                    if not msg.content:
                        entry["content"] = None
                api_messages.append(entry)
            elif msg.role == Role.TOOL and msg.tool_result:
                api_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_result.tool_call_id,
                        "content": msg.tool_result.content,
                    }
                )

        return api_messages

    def _format_tools(self, tools: list[ToolSchema]) -> list[dict[str, Any]]:
        """Convert generic tool schemas to OpenAI function calling format."""
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

    def _parse_response(self, raw: Any) -> Response:
        """Parse OpenAI API response into generic Response."""
        choice = raw.choices[0]
        message = choice.message

        tool_calls: list[ToolCall] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        return Response(
            content=message.content or "",
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=raw.usage.prompt_tokens,
                output_tokens=raw.usage.completion_tokens,
            ),
            model=raw.model,
            stop_reason=choice.finish_reason or "",
        )

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Response:
        """Generate a completion using OpenAI.
        
        Auto-detects whether the model needs max_tokens or max_completion_tokens,
        retrying with the fallback parameter on 400 errors.
        """
        if not self.client:
            raise RuntimeError("OpenAI API key not configured")

        api_messages = self._format_messages(messages)
        base_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
        }
        if tools:
            base_kwargs["tools"] = self._format_tools(tools)

        # Build parameters — try preferred first, fallback on error
        token_params = self._build_token_params(temperature, max_tokens)

        try:
            raw = await self.client.chat.completions.create(**base_kwargs, **token_params)
        except openai.BadRequestError as e:
            error_msg = str(e).lower()
            if "max_tokens" in error_msg or "max_completion_tokens" in error_msg or "unsupported" in error_msg or "temperature" in error_msg:
                fallback_params = dict(token_params)
                
                if "temperature" in error_msg:
                    # It's a temperature error, just remove temperature
                    if "temperature" in fallback_params:
                        fallback_params.pop("temperature")
                else:
                    # It's a token parameter error, swap them
                    if "max_completion_tokens" in fallback_params:
                        fallback_params["max_tokens"] = fallback_params.pop("max_completion_tokens")
                    elif "max_tokens" in fallback_params:
                        fallback_params["max_completion_tokens"] = fallback_params.pop("max_tokens")

                raw = await self.client.chat.completions.create(**base_kwargs, **fallback_params)
            else:
                raise

        response = self._parse_response(raw)
        self._last_usage = response.usage
        return response

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion from OpenAI."""
        if not self.client:
            raise RuntimeError("OpenAI API key not configured")

        api_messages = self._format_messages(messages)
        base_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            base_kwargs["tools"] = self._format_tools(tools)

        token_params = self._build_token_params(temperature, max_tokens)

        try:
            stream = await self.client.chat.completions.create(**base_kwargs, **token_params)
        except openai.BadRequestError as e:
            error_msg = str(e).lower()
            if "max_tokens" in error_msg or "max_completion_tokens" in error_msg or "unsupported" in error_msg or "temperature" in error_msg:
                fallback_params = dict(token_params)

                if "temperature" in error_msg:
                    # It's a temperature error, just remove temperature
                    if "temperature" in fallback_params:
                        fallback_params.pop("temperature")
                else:
                    # It's a token parameter error, swap them
                    if "max_completion_tokens" in fallback_params:
                        fallback_params["max_tokens"] = fallback_params.pop("max_completion_tokens")
                    elif "max_tokens" in fallback_params:
                        fallback_params["max_completion_tokens"] = fallback_params.pop("max_tokens")

                stream = await self.client.chat.completions.create(**base_kwargs, **fallback_params)
            else:
                raise
        async for chunk in stream:
            if not chunk.choices:
                # Final chunk with usage data
                if chunk.usage:
                    yield StreamChunk(
                        is_final=True,
                        usage=Usage(
                            input_tokens=chunk.usage.prompt_tokens,
                            output_tokens=chunk.usage.completion_tokens,
                        ),
                    )
                continue

            delta = chunk.choices[0].delta
            if delta.content:
                yield StreamChunk(content=delta.content)

            if chunk.choices[0].finish_reason:
                yield StreamChunk(is_final=True)

    def get_cost(self, usage: Usage) -> float:
        """Calculate cost based on OpenAI pricing."""
        pricing = PRICING.get(self.model, {"input": 2.50, "output": 10.0})
        input_cost = (usage.input_tokens / 1_000_000) * pricing["input"]
        output_cost = (usage.output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    async def list_models(self) -> list[str]:
        """List available OpenAI models."""
        return list(PRICING.keys())
