"""T3 Executor — local SLM for fast, simple actions."""

from __future__ import annotations

import json
from typing import Any

from cascade.core.escalation import EscalationPolicy
from cascade.core.task import SubTask
from cascade.providers.base import (
    BaseProvider,
    Message,
    Role,
)
from cascade.tools.base import Tier, ToolRegistry


EXECUTOR_SYSTEM_PROMPT = """You are a T3 Executor in the Cascade multi-tier AI system.

You are a fast, local agent that handles simple, well-defined tasks.

Your capabilities are limited to:
- Reading files
- Listing directories
- Searching code (grep)
- Finding files by name

Guidelines:
- Execute the task directly and efficiently
- If the task requires writing files, running commands, or making complex decisions, respond with: ESCALATE: [reason]
- Keep your responses concise
- Use tools when needed, then provide a brief result summary

When using tools, respond with a tool call. When done, provide your final answer.
"""


class Executor:
    """T3 Executor — handles simple tasks using local SLM."""

    def __init__(
        self,
        provider: BaseProvider,
        tool_registry: ToolRegistry,
        escalation_policy: EscalationPolicy,
        max_iterations: int = 5,
        cost_callback: Any = None,
    ):
        self.provider = provider
        self.tool_registry = tool_registry
        self.escalation_policy = escalation_policy
        self.max_iterations = max_iterations
        self.cost_callback = cost_callback

    async def execute_subtask(
        self,
        subtask: SubTask,
        context: str = "",
        on_tool_call: Any = None,
        on_thinking: Any = None,
    ) -> tuple[bool, str, float]:
        """
        Execute a simple subtask using the local SLM.

        Returns (success, result_text, confidence_score).
        """
        tool_schemas = self.tool_registry.get_schemas_for_tier(Tier.T3)

        messages: list[Message] = [
            Message(role=Role.SYSTEM, content=EXECUTOR_SYSTEM_PROMPT),
        ]

        user_msg = f"## Task\n{subtask.description}"
        if context:
            user_msg += f"\n\n## Context\n{context}"
        messages.append(Message(role=Role.USER, content=user_msg))

        confidence = 0.8  # Start slightly lower for T3
        errors: list[str] = []

        for iteration in range(self.max_iterations):
            try:
                # Check if provider supports tools
                if self.provider.supports_tools() and tool_schemas:
                    response = await self.provider.generate(
                        messages=messages,
                        tools=tool_schemas,
                        temperature=0.1,
                        max_tokens=2048,
                    )
                else:
                    response = await self.provider.generate(
                        messages=messages,
                        temperature=0.1,
                        max_tokens=2048,
                    )
            except Exception as e:
                errors.append(f"SLM error: {e}")
                confidence -= 0.3
                break

            cost = self.provider.get_cost(response.usage)
            if self.cost_callback:
                self.cost_callback("t3", cost)

            # Check for explicit escalation request
            if response.content and "ESCALATE:" in response.content.upper():
                reason = response.content.split("ESCALATE:", 1)[-1].strip()
                subtask.mark_escalated(reason)
                return False, f"Self-escalated: {reason}", confidence

            # If no tool calls, the agent is done
            if not response.tool_calls:
                if on_thinking and response.content:
                    await on_thinking(response.content)
                return True, response.content, confidence

            # Process tool calls
            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )

            if on_thinking and response.content:
                await on_thinking(response.content)

            for tc in response.tool_calls:
                if on_tool_call:
                    await on_tool_call(tc.name, tc.arguments)

                result = await self.tool_registry.execute(
                    name=tc.name, tier=Tier.T3, **tc.arguments
                )

                if not result.success:
                    errors.append(f"Tool {tc.name} failed: {result.error}")
                    confidence -= 0.2

                from cascade.providers.base import ToolResult as ProviderToolResult
                messages.append(
                    Message(
                        role=Role.TOOL,
                        tool_result=ProviderToolResult(
                            tool_call_id=tc.id,
                            name=tc.name,
                            content=result.output if result.success else f"ERROR: {result.error}",
                            is_error=not result.success,
                        ),
                    )
                )

                subtask.tool_calls_made += 1

            # Check escalation
            should_escalate, reason = self.escalation_policy.should_t3_escalate(
                confidence=confidence,
                retries=len(errors),
                error=errors[-1] if errors else "",
            )
            if should_escalate:
                subtask.mark_escalated(reason)
                return False, reason, confidence

        # If we broke due to errors, report the actual error
        if errors:
            reason = f"SLM errors: {'; '.join(errors[-3:])}"
        else:
            reason = f"Exceeded max iterations ({self.max_iterations})"
        subtask.mark_escalated(reason)
        return False, reason, confidence
