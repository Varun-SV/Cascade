"""T1 Orchestrator — the strategic brain."""

from __future__ import annotations

import json
import uuid
from typing import Any

from cascade.core.escalation import EscalationContext, EscalationPolicy
from cascade.core.task import SubTask, TaskPlan, TierAssignment
from cascade.providers.base import BaseProvider, Message, Role, ToolSchema
from cascade.tools.base import ToolRegistry


ORCHESTRATOR_SYSTEM_PROMPT = """You are the T1 Orchestrator in a multi-tier AI agent system called Cascade.

Your role is to:
1. Analyze user requests and break them into subtasks
2. Assign each subtask to the appropriate tier:
   - T3 (local SLM): Simple, well-defined tasks like reading files, searching code, formatting
   - T2 (cloud worker): Most coding tasks — file edits, running commands, git operations, web searches
   - T1 (you): Only for complex architectural decisions, ambiguous requirements, or re-planning after escalation
3. Create a clear execution plan with dependencies between subtasks

When decomposing tasks, think about:
- What information needs to be gathered first (assign to T3 for reading, T2 for complex analysis)
- What actions need to be taken (assign to T2)
- What decisions require complex reasoning (keep for T1)

IMPORTANT: You must respond with a valid JSON object containing:
{
  "reasoning": "Your analysis of the task and decomposition strategy",
  "summary": "Brief summary of the plan",
  "subtasks": [
    {
      "id": "subtask_1",
      "description": "Clear, actionable description",
      "assigned_tier": "t2",
      "dependencies": []
    },
    ...
  ]
}
"""

ESCALATION_SYSTEM_PROMPT = """You are the T1 Orchestrator handling an escalation from a lower tier.

A {from_tier} agent could not complete a task and needs your help.

Escalation reason: {reason}
Task: {task_description}
Attempts made: {attempts}
Errors encountered: {errors}
Partial result: {partial_result}

Please analyze the situation and provide one of:
1. Revised instructions for the lower tier to retry
2. A new decomposition of the remaining work
3. Direct resolution if the task requires your capabilities

Respond with a JSON object:
{{
  "action": "retry" | "redecompose" | "resolve",
  "instructions": "Clear instructions for retry or resolution",
  "subtasks": [...],  // Only if action is "redecompose"
  "resolution": "..."  // Only if action is "resolve"
}}
"""


class Orchestrator:
    """T1 Orchestrator — decomposes tasks and handles escalations."""

    def __init__(
        self,
        provider: BaseProvider,
        tool_registry: ToolRegistry,
        escalation_policy: EscalationPolicy,
    ):
        self.provider = provider
        self.tool_registry = tool_registry
        self.escalation_policy = escalation_policy

    async def decompose_task(
        self, task_description: str, project_context: str = ""
    ) -> TaskPlan:
        """Decompose a user request into a plan of subtasks."""
        messages = [
            Message(role=Role.SYSTEM, content=ORCHESTRATOR_SYSTEM_PROMPT),
            Message(
                role=Role.USER,
                content=self._build_decompose_prompt(task_description, project_context),
            ),
        ]

        response = await self.provider.generate(
            messages=messages,
            temperature=0.3,
            max_tokens=4096,
        )

        return self._parse_plan(response.content)

    async def handle_escalation(
        self, context: EscalationContext
    ) -> dict[str, Any]:
        """Handle an escalation from a lower tier."""
        prompt = ESCALATION_SYSTEM_PROMPT.format(
            from_tier=context.failed_model,
            reason=context.reason,
            task_description=context.task_description,
            attempts=context.attempts,
            errors="\n".join(context.errors) if context.errors else "None",
            partial_result="None",
        )

        messages = [
            Message(role=Role.SYSTEM, content=prompt),
            Message(
                role=Role.USER,
                content="Please analyze this escalation and provide guidance.",
            ),
        ]

        response = await self.provider.generate(
            messages=messages,
            temperature=0.3,
            max_tokens=4096,
        )

        return self._parse_escalation_response(response.content)

    def _build_decompose_prompt(
        self, task_description: str, project_context: str
    ) -> str:
        """Build the prompt for task decomposition."""
        prompt = f"## User Request\n{task_description}\n"

        if project_context:
            prompt += f"\n## Project Context\n{project_context}\n"

        available_tools = self.tool_registry.list_all()
        prompt += f"\n## Available Tools\n{', '.join(available_tools)}\n"

        prompt += (
            "\nPlease decompose this request into subtasks. "
            "Assign each to the appropriate tier (t1, t2, or t3). "
            "Include dependencies where subtasks depend on outputs from other subtasks."
        )

        return prompt

    def _parse_plan(self, content: str) -> TaskPlan:
        """Parse LLM response into a TaskPlan."""
        try:
            # Try to extract JSON from the response
            json_str = self._extract_json(content)
            data = json.loads(json_str)

            subtasks = []
            for i, st_data in enumerate(data.get("subtasks", [])):
                subtask_id = st_data.get("id", f"subtask_{i + 1}")
                tier_str = st_data.get("assigned_tier", "t2").lower()
                tier = TierAssignment.T2
                if tier_str == "t1":
                    tier = TierAssignment.T1
                elif tier_str == "t3":
                    tier = TierAssignment.T3

                subtasks.append(
                    SubTask(
                        id=subtask_id,
                        description=st_data.get("description", ""),
                        assigned_tier=tier,
                        dependencies=st_data.get("dependencies", []),
                    )
                )

            return TaskPlan(
                subtasks=subtasks,
                summary=data.get("summary", ""),
                reasoning=data.get("reasoning", ""),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            # Fallback: create a single T2 subtask with the original description
            return TaskPlan(
                subtasks=[
                    SubTask(
                        id="subtask_1",
                        description=content,
                        assigned_tier=TierAssignment.T2,
                    )
                ],
                summary="Single-task plan (failed to decompose)",
                reasoning="Could not parse structured plan from LLM response",
            )

    def _parse_escalation_response(self, content: str) -> dict[str, Any]:
        """Parse escalation response from LLM."""
        try:
            json_str = self._extract_json(content)
            return json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            return {
                "action": "resolve",
                "resolution": content,
            }

    @staticmethod
    def _extract_json(content: str) -> str:
        """Extract JSON from potentially wrapped content."""
        content = content.strip()

        # Try to find JSON block in markdown code fence
        if "```json" in content:
            start = content.index("```json") + 7
            end = content.index("```", start)
            return content[start:end].strip()
        elif "```" in content:
            start = content.index("```") + 3
            end = content.index("```", start)
            return content[start:end].strip()

        # Try to find raw JSON object
        if "{" in content:
            start = content.index("{")
            # Find matching closing brace
            depth = 0
            for i in range(start, len(content)):
                if content[i] == "{":
                    depth += 1
                elif content[i] == "}":
                    depth -= 1
                    if depth == 0:
                        return content[start : i + 1]

        return content
