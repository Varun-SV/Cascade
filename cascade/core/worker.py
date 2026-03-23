"""T2 Worker — the tool-using execution agent."""

from __future__ import annotations

import json
from typing import Any

from cascade.core.escalation import EscalationContext, EscalationPolicy
from cascade.core.task import SubTask
from cascade.providers.base import (
    BaseProvider,
    Message,
    Response,
    Role,
    ToolSchema,
)
from cascade.tools.base import Tier, ToolRegistry, ToolResult


WORKER_SYSTEM_PROMPT = """You are a T2 Worker agent in the Cascade multi-tier AI system.

Your role is to execute specific subtasks using the tools available to you.

Guidelines:
- Focus on completing the assigned subtask efficiently
- Use tools to gather information, make changes, and verify your work
- If you encounter something beyond your capabilities or unclear requirements, say so clearly
- After completing the task, provide a clear summary of what you did

When you need to use a tool, respond with a tool call. After receiving the result, continue working.

When the task is complete, respond with your final summary WITHOUT making any tool calls.

Important:
- Always verify your changes work (e.g., read back edited files)
- If a tool call fails, try an alternative approach before giving up
- Be precise with file paths and code edits
"""


class Worker:
    """T2 Worker — executes subtasks using tools in an agent loop."""

    def __init__(
        self,
        provider: BaseProvider,
        tool_registry: ToolRegistry,
        escalation_policy: EscalationPolicy,
        max_iterations: int = 15,
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
        Execute a subtask in an agent loop.

        Returns (success, result_text, confidence_score).
        """
        tool_schemas = self.tool_registry.get_schemas_for_tier(Tier.T2)
        messages: list[Message] = [
            Message(role=Role.SYSTEM, content=WORKER_SYSTEM_PROMPT),
        ]

        # Build the initial user message
        user_msg = f"## Subtask\n{subtask.description}"
        if context:
            user_msg += f"\n\n## Context\n{context}"
        messages.append(Message(role=Role.USER, content=user_msg))

        confidence = 1.0
        errors: list[str] = []
        total_cost = 0.0

        for iteration in range(self.max_iterations):
            # Generate LLM response
            try:
                response = await self.provider.generate(
                    messages=messages,
                    tools=tool_schemas,
                    temperature=0.2,
                    max_tokens=4096,
                )
            except Exception as e:
                errors.append(f"LLM error: {e}")
                confidence -= 0.3
                break

            cost = self.provider.get_cost(response.usage)
            total_cost += cost
            if self.cost_callback:
                self.cost_callback("t2", cost)

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

                # Execute the tool
                result = await self.tool_registry.execute(
                    name=tc.name, tier=Tier.T2, **tc.arguments
                )

                if not result.success:
                    errors.append(f"Tool {tc.name} failed: {result.error}")
                    confidence -= 0.15

                # Add tool result to conversation
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
            should_escalate, reason = self.escalation_policy.should_t2_escalate(
                confidence=confidence,
                retries=len(errors),
                error=errors[-1] if errors else "",
            )
            if should_escalate:
                subtask.mark_escalated(reason)
                return False, reason, confidence

        # If we broke due to errors, report the actual error
        if errors:
            reason = f"LLM/tool errors: {'; '.join(errors[-3:])}"
        else:
            reason = f"Exceeded max iterations ({self.max_iterations})"
        subtask.mark_escalated(reason)
        return False, reason, confidence

    async def execute_with_instructions(
        self,
        instructions: str,
        subtask: SubTask,
        on_tool_call: Any = None,
        on_thinking: Any = None,
    ) -> tuple[bool, str, float]:
        """Execute a subtask with specific instructions (e.g., from T1 after escalation)."""
        subtask.retries += 1
        context = f"Previous attempt failed. New instructions from orchestrator:\n{instructions}"
        return await self.execute_subtask(
            subtask, context=context, on_tool_call=on_tool_call, on_thinking=on_thinking
        )
