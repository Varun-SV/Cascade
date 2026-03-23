"""Dynamic Recursive Agent for the N-Tier Fractal architecture."""

from __future__ import annotations

import json
from typing import Any, Callable

from cascade.config import CascadeConfig
from cascade.core.escalation import EscalationContext, EscalationPolicy
from cascade.core.task import SubTask, TaskStatus
from cascade.providers.base import (
    BaseProvider,
    Message,
    Role,
    ToolSchema,
    ToolResult as ProviderToolResult,
)
from cascade.tools.base import ToolRegistry

DELEGATE_TOOL_SCHEMA = ToolSchema(
    name="delegate_task",
    description="Delegate a complex subtask to a new child agent. Use this when a task is too complex, requires finding more information before proceeding, or you want a specialized model to handle it.",
    parameters={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Clear instructions for the child agent"},
            "model_id": {"type": "string", "description": "Which model to assign (e.g., 'worker', 'local')"},
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of tool names to grant. Pass ['all'] to grant all your tools."
            }
        },
        "required": ["description", "model_id", "tools"]
    }
)

AGENT_SYSTEM_PROMPT = """You are a Cascade AI Agent ({model_id}).

Your role is to complete the assigned task using the tools provided.
If the task is simple and you have the right tools, execute it directly.
If the task is highly complex, breaks down into many distinct parts, or requires capabilities you don't have, you can use the `delegate_task` tool to spawn child agents to help you.

Available Models for Delegation:
{models_list}

Important Guidelines:
- Execute what you can; delegate what is complex or outside your tool scope.
- Wait for tool results (including `delegate_task`) before proceeding.
- When you are completely finished, provide a concise summary of what was accomplished without making any tool calls.
- Always verify your work when editing code.
"""

class CascadeAgent:
    """A recursive, fractal agent capable of execution and delegation."""

    def __init__(
        self,
        model_id: str,
        provider: BaseProvider,
        config: CascadeConfig,
        tool_registry: ToolRegistry,
        escalation_policy: EscalationPolicy,
        allowed_tools: list[str],
        provider_factory: Callable[[str], BaseProvider],
        max_iterations: int = 30,
        cost_callback: Any = None,
    ):
        self.model_id = model_id
        self.provider = provider
        self.config = config
        self.tool_registry = tool_registry
        self.escalation_policy = escalation_policy
        self.allowed_tools = allowed_tools
        self.provider_factory = provider_factory
        self.max_iterations = max_iterations
        self.cost_callback = cost_callback

    def _get_system_prompt(self) -> str:
        models_info = []
        for m in self.config.models:
            models_info.append(f"- {m.id} ({m.provider}/{m.model})")
        
        return AGENT_SYSTEM_PROMPT.format(
            model_id=self.model_id,
            models_list="\n".join(models_info),
        )

    async def execute_subtask(
        self,
        subtask: SubTask,
        context: str = "",
        on_tool_call: Any = None,
        on_thinking: Any = None,
        on_agent_spawn: Any = None,
        on_auditor_block: Any = None,
        on_tool_result: Any = None,
    ) -> tuple[bool, str, float]:
        """Execute the subtask."""
        # Get standard tool schemas
        standard_schemas = self.tool_registry.get_schemas(self.allowed_tools)
        # Add the special delegation tool
        tool_schemas = standard_schemas + [DELEGATE_TOOL_SCHEMA]

        messages: list[Message] = [
            Message(role=Role.SYSTEM, content=self._get_system_prompt()),
        ]

        user_msg = f"## Assigned Task\n{subtask.description}"
        if context:
            user_msg += f"\n\n## Context\n{context}"
        messages.append(Message(role=Role.USER, content=user_msg))

        confidence = 1.0
        errors: list[str] = []
        consecutive_tool_failures = 0

        for iteration in range(self.max_iterations):
            try:
                model_config = self.config.get_model(self.model_id)
                response = await self.provider.generate(
                    messages=messages,
                    tools=tool_schemas,
                    temperature=model_config.temperature,
                    max_tokens=model_config.max_tokens,
                )
            except Exception as e:
                errors.append(f"LLM error: {e}")
                confidence -= 0.3
                break

            if response.usage and self.cost_callback:
                cost = self.provider.get_cost(response.usage)
                self.cost_callback(self.model_id, cost)

            if not response.tool_calls:
                if on_thinking and response.content:
                    await on_thinking(response.content)
                return True, response.content or "Completed with no output.", confidence

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
                subtask.tool_calls_made += 1
                
                # Check if it is a delegation call
                if tc.name == "delegate_task":
                    # Handle delegation internally!
                    if on_agent_spawn:
                        await on_agent_spawn(
                            self.model_id, 
                            tc.arguments.get("model_id", "unknown"),
                            tc.arguments.get("description", "")
                        )
                        
                    child_result_str, child_success = await self._handle_delegation(
                        tc.arguments, 
                        on_tool_call, 
                        on_thinking, 
                        on_agent_spawn,
                        on_auditor_block,
                        on_tool_result
                    )
                    
                    if child_success:
                        consecutive_tool_failures = 0
                    else:
                        consecutive_tool_failures += 1
                        confidence -= 0.1
                        
                    messages.append(
                        Message(
                            role=Role.TOOL,
                            tool_result=ProviderToolResult(
                                tool_call_id=tc.id,
                                name=tc.name,
                                content=child_result_str,
                                is_error=not child_success,
                            ),
                        )
                    )
                    continue

                # Auditor Intervention Check
                if tc.name in ["run_command", "write_file", "edit_file", "git_commit"]:
                    if self.config.default_auditor:
                        from cascade.core.auditor import AuditorAgent
                        try:
                            aud_provider = self.provider_factory(self.config.default_auditor)
                            auditor = AuditorAgent(aud_provider)
                            act_thinking = response.content or "No thinking provided."
                            safe, aud_reason = await auditor.evaluate_tool(
                                task_description=subtask.description,
                                agent_thought=act_thinking,
                                tool_name=tc.name,
                                tool_args=tc.arguments,
                            )
                            if not safe:
                                errors.append(f"Tool {tc.name} blocked by Auditor: {aud_reason}")
                                consecutive_tool_failures += 1
                                confidence -= 0.15
                                
                                if on_auditor_block:
                                    await on_auditor_block(tc.name, aud_reason)
                                    
                                messages.append(
                                    Message(
                                        role=Role.TOOL,
                                        tool_result=ProviderToolResult(
                                            tool_call_id=tc.id,
                                            name=tc.name,
                                            content=f"ERROR: Execution Blocked by Auditor. Reason: {aud_reason}",
                                            is_error=True,
                                        ),
                                    )
                                )
                                continue
                        except Exception as e:
                            # if auditor fails, allow standard tool
                            pass

                # Standard tool call
                if on_tool_call:
                    await on_tool_call(tc.name, tc.arguments)

                result = await self.tool_registry.execute(
                    name=tc.name,
                    allowed_names=self.allowed_tools,
                    **tc.arguments
                )

                if not result.success:
                    consecutive_tool_failures += 1
                    errors.append(f"Tool {tc.name} failed: {result.error}")
                    confidence -= 0.15
                else:
                    consecutive_tool_failures = 0

                if on_tool_result:
                    out_text = result.error if not result.success else result.output
                    await on_tool_result(tc.name, result.success, out_text)

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

            # Check escalation
            if self.escalation_policy.should_escalate(confidence, len(errors), consecutive_tool_failures):
                reason = "Agent lost confidence or faced too many failures."
                subtask.mark_escalated(reason)
                return False, reason, confidence

        reason = f"Exceeded max iterations ({self.max_iterations})"
        subtask.mark_escalated(reason)
        return False, reason, confidence

    async def _handle_delegation(
        self, 
        args: dict[str, Any],
        on_tool_call: Any,
        on_thinking: Any,
        on_agent_spawn: Any,
        on_auditor_block: Any,
        on_tool_result: Any,
    ) -> tuple[str, bool]:
        """Create and run a child agent."""
        desc = args.get("description", "")
        child_model_id = args.get("model_id", "")
        tools = args.get("tools", [])

        try:
            self.config.get_model(child_model_id)
        except ValueError:
            return f"Error: Model '{child_model_id}' does not exist.", False

        try:
            child_provider = self.provider_factory(child_model_id)
        except Exception as e:
            return f"Error initializing child provider: {e}", False

        # If child requested 'all' but parent doesn't have 'all', restrict it
        if tools == ["all"]:
            child_tools = self.allowed_tools
        else:
            # Only grant tools the parent itself holds
            if self.allowed_tools == ["all"]:
                child_tools = tools
            else:
                child_tools = [t for t in tools if t in self.allowed_tools]
                
        child_task = SubTask(
            description=desc,
            assigned_model=child_model_id,
            assigned_tools=child_tools,
        )

        child_agent = CascadeAgent(
            model_id=child_model_id,
            provider=child_provider,
            config=self.config,
            tool_registry=self.tool_registry,
            escalation_policy=self.escalation_policy,
            allowed_tools=child_tools,
            provider_factory=self.provider_factory,
            max_iterations=self.max_iterations,
            cost_callback=self.cost_callback,
        )

        success, result_text, conf = await child_agent.execute_subtask(
            child_task, 
            on_tool_call=on_tool_call, 
            on_thinking=on_thinking,
            on_agent_spawn=on_agent_spawn,
            on_auditor_block=on_auditor_block,
            on_tool_result=on_tool_result,
        )
        
        output = f"Child {child_model_id} finished (Success={success}, Confidence={conf:.2f}):\n{result_text}"
        return output, success
