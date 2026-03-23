"""Google Gemini provider implementation."""

from __future__ import annotations

from typing import Any, AsyncIterator

from google import genai
from google.genai import types

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

# Pricing per million tokens (approximate)
PRICING: dict[str, dict[str, float]] = {
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
}


class GoogleProvider(BaseProvider):
    """Provider for Google Gemini models."""

    def __init__(self, api_key: str = "", model: str = "gemini-2.0-flash", **kwargs: Any):
        super().__init__(api_key=api_key, model=model, **kwargs)
        self.client = genai.Client(api_key=api_key) if api_key else None

    def _format_contents(
        self, messages: list[Message]
    ) -> tuple[str | None, list[types.Content]]:
        """Convert generic messages to Gemini format. Returns (system_instruction, contents)."""
        system_instruction: str | None = None
        contents: list[types.Content] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                system_instruction = msg.content
            elif msg.role == Role.USER:
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=msg.content)],
                    )
                )
            elif msg.role == Role.ASSISTANT:
                parts: list[types.Part] = []
                if msg.content:
                    parts.append(types.Part.from_text(text=msg.content))
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        parts.append(
                            types.Part.from_function_call(
                                name=tc.name, args=tc.arguments
                            )
                        )
                contents.append(types.Content(role="model", parts=parts))
            elif msg.role == Role.TOOL and msg.tool_result:
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=msg.tool_result.name,
                                response={"result": msg.tool_result.content},
                            )
                        ],
                    )
                )

        return system_instruction, contents

    def _format_tools(self, tools: list[ToolSchema]) -> list[types.Tool]:
        """Convert generic tool schemas to Gemini format."""
        declarations = []
        for t in tools:
            declarations.append(
                types.FunctionDeclaration(
                    name=t.name,
                    description=t.description,
                    parameters=t.parameters if t.parameters else None,
                )
            )
        return [types.Tool(function_declarations=declarations)]

    def _parse_response(self, raw: Any) -> Response:
        """Parse Gemini response into generic Response."""
        content = ""
        tool_calls: list[ToolCall] = []

        if raw.candidates and raw.candidates[0].content:
            for part in raw.candidates[0].content.parts:
                if part.text:
                    content += part.text
                elif part.function_call:
                    tool_calls.append(
                        ToolCall(
                            id=part.function_call.name,
                            name=part.function_call.name,
                            arguments=dict(part.function_call.args) if part.function_call.args else {},
                        )
                    )

        usage = Usage()
        if raw.usage_metadata:
            usage = Usage(
                input_tokens=raw.usage_metadata.prompt_token_count or 0,
                output_tokens=raw.usage_metadata.candidates_token_count or 0,
            )

        return Response(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=self.model,
            stop_reason=str(raw.candidates[0].finish_reason) if raw.candidates else "",
        )

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Response:
        """Generate a completion using Gemini."""
        if not self.client:
            raise RuntimeError("Google API key not configured")

        system_instruction, contents = self._format_contents(messages)

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_instruction,
        )

        if tools:
            config.tools = self._format_tools(tools)

        raw = await self.client.aio.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )
        return self._parse_response(raw)

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion from Gemini."""
        if not self.client:
            raise RuntimeError("Google API key not configured")

        system_instruction, contents = self._format_contents(messages)

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_instruction,
        )

        if tools:
            config.tools = self._format_tools(tools)

        async for chunk in await self.client.aio.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=config,
        ):
            if chunk.candidates and chunk.candidates[0].content:
                for part in chunk.candidates[0].content.parts:
                    if part.text:
                        yield StreamChunk(content=part.text)

            if chunk.candidates and chunk.candidates[0].finish_reason:
                usage = Usage()
                if chunk.usage_metadata:
                    usage = Usage(
                        input_tokens=chunk.usage_metadata.prompt_token_count or 0,
                        output_tokens=chunk.usage_metadata.candidates_token_count or 0,
                    )
                yield StreamChunk(is_final=True, usage=usage)

    def get_cost(self, usage: Usage) -> float:
        """Calculate cost based on Gemini pricing."""
        pricing = PRICING.get(self.model, {"input": 0.10, "output": 0.40})
        input_cost = (usage.input_tokens / 1_000_000) * pricing["input"]
        output_cost = (usage.output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    async def list_models(self) -> list[str]:
        """List available Gemini models."""
        return list(PRICING.keys())
