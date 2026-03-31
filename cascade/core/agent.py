"""Recursive agent runtime with working memory, reflection, and structured delegation."""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable

from cascade.config import CascadeConfig
from cascade.core.approval import ApprovalHandler
from cascade.core.escalation import EscalationPolicy
from cascade.core.events import EventBus
from cascade.core.runtime import (
    DelegationEnvelope,
    EventLevel,
    ExecutionContext,
    ExecutionEvent,
    RetryReflection,
    WorkingMemory,
)
from cascade.core.task import SubTask
from cascade.observability.rollback import RollbackManager
from cascade.providers.base import (
    BaseProvider,
    Message,
    Role,
    ToolResult as ProviderToolResult,
    ToolSchema,
)
from cascade.tools.base import ToolRegistry

DELEGATE_TOOL_SCHEMA = ToolSchema(
    name="delegate_task",
    description=(
        "Delegate a subtask to a child Cascade agent. Use this when a task needs "
        "its own focused context, tool budget, or model specialization."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short title for the delegated subtask.",
            },
            "goal": {
                "type": "string",
                "description": "What the child agent should accomplish.",
            },
            "description": {
                "type": "string",
                "description": "Backward-compatible alias for goal.",
            },
            "model_id": {
                "type": "string",
                "description": "Which configured model should run this subtask.",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific tools the child may use. Prefer narrow grants over ['all'].",
            },
            "constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Important constraints the child must preserve.",
            },
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string"},
                "description": "What must be true for the subtask to count as complete.",
            },
            "expected_output_schema": {
                "type": "object",
                "description": "Optional JSON-like schema describing the expected final answer.",
            },
            "budget_ceiling": {
                "type": "number",
                "description": "Optional maximum budget allocation for this child task.",
            },
            "context_notes": {
                "type": "string",
                "description": "Relevant context or discoveries to include in the handoff.",
            },
            "repo_context": {
                "type": "string",
                "description": "Important repository context for the child agent.",
            },
        },
        "required": ["title", "model_id", "tools"],
    },
)

AGENT_SYSTEM_PROMPT = """You are a Cascade AI agent named {agent_id} running model pool entry `{model_id}`.

You are executing a real software engineering task inside a guarded agent runtime.

Available tools right now:
{current_tools_list}

Available models for delegation:
{models_list}

Available tools you may grant to child agents:
{delegation_tools_list}

Working memory snapshot:
{working_memory}

Runtime expectations:
1. Prefer fast discovery before deep reading. Use `find_files`, `glob_files`, `grep_search`, and `semantic_code_search` before broad reads.
2. Use `read_files` when you need multi-file context and `diff_preview` before risky edits.
3. Prefer `search_replace` or `apply_patch` for code edits, and verify changes afterwards.
4. When a subtask deserves isolated focus, call `delegate_task` with explicit constraints, allowed tools, acceptance criteria, and output expectations.
5. If a previous attempt failed, learn from the reflection notes instead of repeating the same action.
6. Your final answer must summarize what changed, what was verified, and any remaining risk.
"""


class CascadeAgent:
    """A recursive agent capable of direct execution and structured delegation."""

    def __init__(
        self,
        model_id: str,
        provider: BaseProvider,
        config: CascadeConfig,
        tool_registry: ToolRegistry,
        escalation_policy: EscalationPolicy,
        allowed_tools: list[str],
        provider_factory: Callable[..., BaseProvider],
        max_iterations: int = 30,
        cost_callback: Any = None,
        approval_handler: ApprovalHandler | None = None,
        event_bus: EventBus | None = None,
        execution_context: ExecutionContext | None = None,
        rollback_manager: RollbackManager | None = None,
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
        self.approval_handler = approval_handler
        self.event_bus = event_bus
        self.execution_context = execution_context
        self.rollback_manager = rollback_manager
        self.agent_id = (
            execution_context.current_agent_id
            if execution_context and execution_context.current_agent_id
            else f"{model_id}:{uuid.uuid4().hex[:8]}"
        )

    async def _emit(
        self,
        event_type: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
        level: EventLevel = EventLevel.INFO,
    ) -> None:
        if not self.event_bus or not self.execution_context:
            return
        await self.event_bus.emit(
            ExecutionEvent(
                event_type=event_type,
                task_id=self.execution_context.task_id,
                session_id=self.execution_context.session_id,
                agent_id=self.agent_id,
                parent_agent_id=str(self.execution_context.metadata.get("parent_agent_id", "")),
                model_id=self.model_id,
                subtask_id=self.execution_context.current_subtask_id,
                level=level,
                message=message,
                payload=payload or {},
            )
        )

    def _get_system_prompt(self, memory: WorkingMemory) -> str:
        models_info = []
        for model in self.config.models:
            models_info.append(f"- {model.id} ({model.provider}/{model.model})")

        current_tools = self.tool_registry.get_tools(self.allowed_tools)
        current_tools_info = [f"- {tool.name}: {tool.description}" for tool in current_tools]
        if not current_tools_info:
            current_tools_info = ["- No direct tools beyond delegate_task."]

        delegation_tools_info = [
            f"- {name}: {tool.description}"
            for name, tool in self.tool_registry._tools.items()
            if name != "delegate_task"
        ]

        memory_lines = [
            f"Goal: {memory.goal}",
            f"Constraints: {', '.join(memory.constraints) if memory.constraints else 'None'}",
            f"Completed: {', '.join(memory.completed_subgoals) if memory.completed_subgoals else 'None'}",
            f"Blockers: {', '.join(memory.blockers) if memory.blockers else 'None'}",
            f"Recent tool results: {' | '.join(memory.recent_tool_results) if memory.recent_tool_results else 'None'}",
        ]
        if memory.reflections:
            latest = memory.reflections[-1]
            memory_lines.append(
                f"Latest reflection: {latest.failure_class} | blocker={latest.blocker} | retry_plan={latest.retry_plan}"
            )

        return AGENT_SYSTEM_PROMPT.format(
            agent_id=self.agent_id,
            model_id=self.model_id,
            current_tools_list="\n".join(current_tools_info),
            models_list="\n".join(models_info),
            delegation_tools_list="\n".join(delegation_tools_info),
            working_memory="\n".join(memory_lines),
        )

    def _build_user_message(self, subtask: SubTask, context: str, memory: WorkingMemory) -> str:
        sections = [f"## Assigned Task\n{subtask.description}"]
        if context:
            sections.append(f"## Context\n{context}")
        if memory.open_questions:
            sections.append("## Open Questions\n" + "\n".join(f"- {item}" for item in memory.open_questions))
        if memory.blockers:
            sections.append("## Known Blockers\n" + "\n".join(f"- {item}" for item in memory.blockers))
        return "\n\n".join(sections)

    def _build_reflection_prompt(self, reflection: RetryReflection, memory: WorkingMemory) -> str:
        evidence = "\n".join(f"- {item}" for item in reflection.evidence) or "- No additional evidence."
        return (
            "The previous attempt did not fully succeed. Reflect and adjust.\n\n"
            f"Failure class: {reflection.failure_class}\n"
            f"Explanation: {reflection.explanation}\n"
            f"Blocker: {reflection.blocker}\n"
            f"Retry plan: {reflection.retry_plan}\n"
            f"Evidence:\n{evidence}\n\n"
            f"Recent working memory:\n"
            f"- Completed subgoals: {', '.join(memory.completed_subgoals) if memory.completed_subgoals else 'None'}\n"
            f"- Recent tool results: {' | '.join(memory.recent_tool_results) if memory.recent_tool_results else 'None'}\n"
            "Do not repeat the failed step unchanged."
        )

    def _make_reflection(
        self,
        *,
        failure_class: str,
        explanation: str,
        evidence: list[str],
        blocker: str,
        retry_plan: str,
    ) -> RetryReflection:
        return RetryReflection(
            failure_class=failure_class,
            explanation=explanation,
            evidence=evidence,
            blocker=blocker,
            retry_plan=retry_plan,
        )

    def _invoke_cost_callback(self, amount: float, *, subtask_id: str = "") -> None:
        if not self.cost_callback or amount <= 0:
            return
        kwargs = {
            "subtask_id": subtask_id,
            "tier": self.model_id,
            "provider": self.config.get_model(self.model_id).provider,
            "task_id": self.execution_context.task_id if self.execution_context else "",
        }
        try:
            self.cost_callback(self.model_id, amount, **kwargs)
        except TypeError:
            self.cost_callback(self.model_id, amount)

    def _make_provider(
        self,
        model_id: str,
        execution_context: ExecutionContext | None = None,
    ) -> BaseProvider:
        try:
            return self.provider_factory(model_id, execution_context)
        except TypeError:
            return self.provider_factory(model_id)

    async def execute_subtask(
        self,
        subtask: SubTask,
        context: str = "",
        on_tool_call: Any = None,
        on_thinking: Any = None,
        on_agent_spawn: Any = None,
        on_auditor_block: Any = None,
        on_tool_result: Any = None,
        on_approval_request: Any = None,
    ) -> tuple[bool, str, float]:
        """Execute a subtask with reflection-aware retries and structured delegation."""
        subtask.mark_in_progress()
        memory = WorkingMemory(goal=subtask.description)
        if context:
            memory.constraints.append("Honor the provided task context while executing.")

        agent_context = self.execution_context
        if agent_context is not None:
            agent_context = agent_context.child(
                agent_id=self.agent_id,
                model_id=self.model_id,
                subtask_id=subtask.id,
            )
            self.execution_context = agent_context

        standard_schemas = self.tool_registry.get_schemas(self.allowed_tools)
        tool_schemas = standard_schemas + [DELEGATE_TOOL_SCHEMA]
        messages: list[Message] = [
            Message(role=Role.SYSTEM, content=self._get_system_prompt(memory)),
            Message(role=Role.USER, content=self._build_user_message(subtask, context, memory)),
        ]

        confidence = 1.0
        errors: list[str] = []
        failed_attempts = 0
        consecutive_tool_failures = 0
        reflection_count = 0

        await self._emit(
            "agent.started",
            f"Agent {self.agent_id} started subtask.",
            payload={"description": subtask.description, "allowed_tools": self.allowed_tools},
        )

        for iteration in range(self.max_iterations):
            messages[0] = Message(role=Role.SYSTEM, content=self._get_system_prompt(memory))
            await self._emit(
                "agent.iteration",
                f"Iteration {iteration + 1} for subtask {subtask.id}.",
                payload={"iteration": iteration + 1},
                level=EventLevel.DEBUG,
            )
            try:
                model_config = self.config.get_model(self.model_id)
                response = await self.provider.generate(
                    messages=messages,
                    tools=tool_schemas,
                    temperature=model_config.temperature,
                    max_tokens=model_config.max_tokens,
                )
            except Exception as error:
                errors.append(f"LLM error: {error}")
                failed_attempts += 1
                confidence -= 0.1
                reflection = self._make_reflection(
                    failure_class="provider_error",
                    explanation="The model provider failed before a usable response was produced.",
                    evidence=[str(error)],
                    blocker="Provider or network failure",
                    retry_plan="Retry with the current working memory and avoid repeating identical requests.",
                )
                memory.blockers.append(reflection.blocker)
                memory.add_reflection(reflection)
                reflection_count += 1
                await self._emit(
                    "agent.reflection",
                    "Captured reflection after provider failure.",
                    payload=reflection.model_dump(),
                    level=EventLevel.WARNING,
                )
                should_give_up = (
                    not self.config.runtime.retry_reflection_enabled
                    or reflection_count > self.config.runtime.max_reflections
                    or self.escalation_policy.should_escalate(
                        confidence,
                        failed_attempts,
                        consecutive_tool_failures,
                    )
                )
                if should_give_up:
                    # If child agents already completed real work, return that
                    # instead of losing everything to a provider failure.
                    if memory.completed_subgoals:
                        summary_parts = [
                            "The agent's provider failed after child agents completed work.",
                            "Completed work:",
                        ]
                        for subgoal in memory.completed_subgoals:
                            summary_parts.append(f"  - {subgoal}")
                        if memory.recent_tool_results:
                            summary_parts.append("Latest results:")
                            for result in memory.recent_tool_results[-3:]:
                                summary_parts.append(f"  - {result}")
                        graceful_result = "\n".join(summary_parts)
                        subtask.mark_completed(graceful_result)
                        await self._emit(
                            "agent.completed",
                            "Agent returned partial results after provider failure.",
                            payload={"confidence": confidence, "partial": True},
                            level=EventLevel.WARNING,
                        )
                        return True, graceful_result, confidence

                    reason = "Provider failure exceeded retry and escalation limits."
                    subtask.mark_escalated(reason)
                    await self._emit(
                        "agent.escalated",
                        reason,
                        payload={"confidence": confidence},
                        level=EventLevel.ERROR,
                    )
                    return False, reason, confidence

                messages = [
                    Message(role=Role.SYSTEM, content=self._get_system_prompt(memory)),
                    *messages[1:],
                    Message(role=Role.USER, content=self._build_reflection_prompt(reflection, memory)),
                ]
                continue

            if response.usage:
                self._invoke_cost_callback(response.usage and self.provider.get_cost(response.usage), subtask_id=subtask.id)

            if on_thinking and response.content:
                await on_thinking(response.content)
            if response.content:
                memory.confidence_signals.append(response.content[:200])
                await self._emit(
                    "agent.response",
                    response.content[:400],
                    payload={"stop_reason": response.stop_reason},
                )

            if not response.tool_calls:
                final_content = response.content.strip() or (
                    "Task processing completed. The agent finished without a detailed summary."
                )
                subtask.mark_completed(final_content)
                await self._emit(
                    "agent.completed",
                    "Agent produced a final answer.",
                    payload={"confidence": confidence},
                )
                return True, final_content, confidence

            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )

            iteration_failures: list[str] = []
            had_success = False

            for tool_call in response.tool_calls:
                subtask.tool_calls_made += 1

                if tool_call.name == "delegate_task":
                    if on_agent_spawn:
                        await on_agent_spawn(
                            self.model_id,
                            str(tool_call.arguments.get("model_id", "unknown")),
                            str(tool_call.arguments.get("title") or tool_call.arguments.get("goal") or ""),
                        )

                    child_result_str, child_success = await self._handle_delegation(
                        tool_call.arguments,
                        on_tool_call,
                        on_thinking,
                        on_agent_spawn,
                        on_auditor_block,
                        on_tool_result,
                        on_approval_request,
                    )

                    if child_success:
                        had_success = True
                        consecutive_tool_failures = 0
                        memory.completed_subgoals.append(
                            str(tool_call.arguments.get("title") or "Delegated subtask")
                        )
                        memory.add_tool_result(child_result_str[:300])
                    else:
                        consecutive_tool_failures += 1
                        confidence -= 0.1
                        iteration_failures.append(child_result_str)
                        errors.append(child_result_str)

                    messages.append(
                        Message(
                            role=Role.TOOL,
                            tool_result=ProviderToolResult(
                                tool_call_id=tool_call.id,
                                name=tool_call.name,
                                content=child_result_str,
                                is_error=not child_success,
                            ),
                        )
                    )
                    continue

                if tool_call.name in {"run_command", "write_file", "edit_file", "git_commit"}:
                    if self.config.auditor_enabled and self.config.default_auditor:
                        from cascade.core.auditor import AuditorAgent

                        try:
                            aud_provider = self._make_provider(self.config.default_auditor, self.execution_context)
                            auditor = AuditorAgent(aud_provider)
                            safe, aud_reason = await auditor.evaluate_tool(
                                task_description=subtask.description,
                                agent_thought=response.content or "No reasoning captured.",
                                tool_name=tool_call.name,
                                tool_args=tool_call.arguments,
                            )
                            if not safe:
                                iteration_failures.append(
                                    f"Tool {tool_call.name} blocked by Auditor: {aud_reason}"
                                )
                                errors.append(iteration_failures[-1])
                                consecutive_tool_failures += 1
                                confidence -= 0.15
                                if on_auditor_block:
                                    await on_auditor_block(tool_call.name, aud_reason)
                                messages.append(
                                    Message(
                                        role=Role.TOOL,
                                        tool_result=ProviderToolResult(
                                            tool_call_id=tool_call.id,
                                            name=tool_call.name,
                                            content=f"ERROR: Execution blocked by Auditor. Reason: {aud_reason}",
                                            is_error=True,
                                        ),
                                    )
                                )
                                await self._emit(
                                    "auditor.blocked",
                                    f"Auditor blocked {tool_call.name}.",
                                    payload={"reason": aud_reason, "tool_name": tool_call.name},
                                    level=EventLevel.WARNING,
                                )
                                continue
                        except Exception:
                            pass

                if on_tool_call:
                    await on_tool_call(tool_call.name, tool_call.arguments)

                result = await self.tool_registry.execute(
                    name=tool_call.name,
                    allowed_names=self.allowed_tools,
                    approval_mode=self.config.approvals.mode,
                    approval_handler=on_approval_request or self.approval_handler,
                    allowed_command_prefixes=self.config.approvals.allowed_command_prefixes,
                    event_bus=self.event_bus,
                    execution_context=self.execution_context,
                    rollback_manager=self.rollback_manager,
                    **tool_call.arguments,
                )

                if result.success:
                    had_success = True
                    consecutive_tool_failures = 0
                    memory.add_tool_result(f"{tool_call.name}: {result.output[:200]}")
                else:
                    consecutive_tool_failures += 1
                    error_text = f"Tool {tool_call.name} failed: {result.error}"
                    iteration_failures.append(error_text)
                    errors.append(error_text)
                    confidence -= 0.15

                if on_tool_result:
                    await on_tool_result(
                        tool_call.name,
                        result.success,
                        result.output if result.success else result.error,
                    )

                messages.append(
                    Message(
                        role=Role.TOOL,
                        tool_result=ProviderToolResult(
                            tool_call_id=tool_call.id,
                            name=tool_call.name,
                            content=result.output if result.success else f"ERROR: {result.error}",
                            is_error=not result.success,
                        ),
                    )
                )

            if iteration_failures:
                failed_attempts += 1
                if self.config.runtime.retry_reflection_enabled:
                    reflection = self._make_reflection(
                        failure_class="tool_failure",
                        explanation="One or more tool executions failed or were blocked.",
                        evidence=iteration_failures[-4:],
                        blocker="Tool execution did not complete cleanly",
                        retry_plan="Use the failure evidence to choose a narrower tool call or delegate the work.",
                    )
                    memory.blockers.append(reflection.blocker)
                    memory.add_reflection(reflection)
                    reflection_count += 1
                    messages = [
                        Message(role=Role.SYSTEM, content=self._get_system_prompt(memory)),
                        *messages[1:],
                        Message(role=Role.USER, content=self._build_reflection_prompt(reflection, memory)),
                    ]
                    await self._emit(
                        "agent.reflection",
                        "Captured reflection after tool failure.",
                        payload=reflection.model_dump(),
                        level=EventLevel.WARNING,
                    )
            elif had_success:
                failed_attempts = 0
                reflection_count = 0

            if self.escalation_policy.should_escalate(
                confidence,
                failed_attempts,
                consecutive_tool_failures,
            ):
                reason = "Agent lost confidence or encountered too many failures."
                subtask.mark_escalated(reason)
                await self._emit(
                    "agent.escalated",
                    reason,
                    payload={"confidence": confidence, "errors": errors[-4:]},
                    level=EventLevel.ERROR,
                )
                return False, reason, confidence

            if reflection_count > self.config.runtime.max_reflections and not had_success:
                reason = "Exceeded maximum reflection attempts without a successful recovery."
                subtask.mark_escalated(reason)
                await self._emit(
                    "agent.escalated",
                    reason,
                    payload={"confidence": confidence},
                    level=EventLevel.ERROR,
                )
                return False, reason, confidence

        reason = f"Exceeded max iterations ({self.max_iterations})."
        subtask.mark_escalated(reason)
        await self._emit(
            "agent.escalated",
            reason,
            payload={"confidence": confidence},
            level=EventLevel.ERROR,
        )
        return False, reason, confidence

    async def _handle_delegation(
        self,
        args: dict[str, Any],
        on_tool_call: Any,
        on_thinking: Any,
        on_agent_spawn: Any,
        on_auditor_block: Any,
        on_tool_result: Any,
        on_approval_request: Any,
    ) -> tuple[str, bool]:
        """Create and run a child agent using a structured delegation envelope."""
        child_model_id = str(args.get("model_id", ""))
        if not child_model_id:
            return "Error: delegate_task requires model_id.", False

        try:
            self.config.get_model(child_model_id)
        except ValueError:
            return f"Error: Model '{child_model_id}' does not exist.", False

        envelope = DelegationEnvelope(
            title=str(args.get("title") or "Delegated task"),
            goal=str(args.get("goal") or args.get("description") or ""),
            constraints=[str(item) for item in args.get("constraints", [])],
            allowed_tools=[str(item) for item in args.get("tools", [])] or ["all"],
            acceptance_criteria=[str(item) for item in args.get("acceptance_criteria", [])],
            expected_output_schema=dict(args.get("expected_output_schema", {})),
            budget_ceiling=args.get("budget_ceiling"),
            context_notes=str(args.get("context_notes", "")),
            repo_context=str(args.get("repo_context", "")),
        )
        if not envelope.goal:
            return "Error: delegate_task requires either goal or description.", False

        child_tools = envelope.allowed_tools if envelope.allowed_tools else ["all"]
        child_task = SubTask(
            id=str(uuid.uuid4())[:8],
            description=envelope.goal,
            assigned_model=child_model_id,
            assigned_tools=child_tools,
        )

        child_agent_id = f"{child_model_id}:{uuid.uuid4().hex[:8]}"
        child_context = None
        if self.execution_context is not None:
            child_context = self.execution_context.child(
                agent_id=child_agent_id,
                model_id=child_model_id,
                subtask_id=child_task.id,
            )
            child_context.metadata = {
                **child_context.metadata,
                "parent_agent_id": self.agent_id,
                "delegation_envelope": envelope.model_dump(),
            }

        try:
            child_provider = self._make_provider(child_model_id, child_context)
        except Exception as error:
            return f"Error initializing child provider: {error}", False

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
            approval_handler=on_approval_request or self.approval_handler,
            event_bus=self.event_bus,
            execution_context=child_context,
            rollback_manager=self.rollback_manager,
        )

        handoff_sections = [
            f"Delegation title: {envelope.title}",
            f"Goal: {envelope.goal}",
        ]
        if envelope.constraints:
            handoff_sections.append(
                "Constraints:\n" + "\n".join(f"- {item}" for item in envelope.constraints)
            )
        if envelope.acceptance_criteria:
            handoff_sections.append(
                "Acceptance criteria:\n"
                + "\n".join(f"- {item}" for item in envelope.acceptance_criteria)
            )
        if envelope.expected_output_schema:
            handoff_sections.append(
                "Expected output schema:\n"
                + json.dumps(envelope.expected_output_schema, indent=2, sort_keys=True)
            )
        if envelope.budget_ceiling is not None:
            handoff_sections.append(f"Budget ceiling: ${float(envelope.budget_ceiling):.4f}")
        if envelope.context_notes:
            handoff_sections.append(f"Context notes:\n{envelope.context_notes}")
        if envelope.repo_context:
            handoff_sections.append(f"Repository context:\n{envelope.repo_context}")

        await self._emit(
            "agent.delegated",
            f"Delegated '{envelope.title}' to {child_model_id}.",
            payload={"envelope": envelope.model_dump()},
        )

        success, result_text, confidence = await child_agent.execute_subtask(
            child_task,
            context="\n\n".join(handoff_sections),
            on_tool_call=on_tool_call,
            on_thinking=on_thinking,
            on_agent_spawn=on_agent_spawn,
            on_auditor_block=on_auditor_block,
            on_tool_result=on_tool_result,
            on_approval_request=on_approval_request,
        )

        output = (
            f"Child agent `{child_agent_id}` finished "
            f"(success={success}, confidence={confidence:.2f}).\n{result_text}"
        )
        return output, success
