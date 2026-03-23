"""Sentinel Auditor Agent logic for evaluating tool execution safety."""

from __future__ import annotations

import json
from typing import Any

from cascade.providers.base import BaseProvider, Message, Role

AUDITOR_SYSTEM_PROMPT = """You are the Sentinel Auditor in the Cascade AI system.
Your only job is to evaluate if a tool call made by another agent is safe to execute on the user's system.

If the command deletes system files, uploads private keys, or seems maliciously destructive, block it.
If the command is a standard development task (creating scripts, reading logs, running tests, compiling), approve it.

You must respond with a JSON object exactly like this:
{
    "safe": true_or_false,
    "reason": "Brief explanation of why it was approved or rejected"
}
"""

class AuditorAgent:
    """Evaluates the safety of high-risk tool executions."""

    def __init__(self, provider: BaseProvider):
        self.provider = provider
        
    async def evaluate_tool(self, task_description: str, agent_thought: str, tool_name: str, tool_args: dict[str, Any]) -> tuple[bool, str]:
        """Check if a tool is safe to execute."""
        
        args_str = json.dumps(tool_args, indent=2)
        prompt = f"""Target Tool: {tool_name}
Tool Arguments:
{args_str}

Agent's internal thinking:
"{agent_thought}"

Original Task Objective:
"{task_description}"

Is this tool execution safe and reasonable for this task?"""

        messages = [
            Message(role=Role.SYSTEM, content=AUDITOR_SYSTEM_PROMPT),
            Message(role=Role.USER, content=prompt),
        ]
        
        try:
            response = await self.provider.generate(
                messages=messages,
                temperature=0.0,
                max_tokens=300,
            )
            
            # Simple JSON extraction
            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].strip()
                
            data = json.loads(content)
            return data.get("safe", False), data.get("reason", "Could not parse auditor response.")
            
        except Exception as e:
            # If the auditor crashes or hallucinated, fail-safe to reject
            return False, f"Auditor failed to evaluate: {e}"
