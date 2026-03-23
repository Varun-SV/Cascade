"""Cascade — Public Python API for programmatic usage."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from cascade.budget.tracker import CostTracker
from cascade.config import CascadeConfig, TierConfig, load_config
from cascade.core.escalation import EscalationContext, EscalationPolicy
from cascade.core.executor import Executor
from cascade.core.orchestrator import Orchestrator
from cascade.core.task import (
    SubTask,
    Task,
    TaskPlan,
    TaskResult,
    TaskStatus,
    TierAssignment,
)
from cascade.core.worker import Worker
from cascade.providers.base import BaseProvider
from cascade.tools.base import ToolRegistry
from cascade.tools.code_search import FindFilesTool, GrepSearchTool
from cascade.tools.file_ops import (
    EditFileTool,
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
)
from cascade.tools.git_ops import GitCommitTool, GitDiffTool, GitLogTool, GitStatusTool
from cascade.tools.shell import RunCommandTool
from cascade.tools.web import FetchURLTool, WebSearchTool
from cascade.utils.logger import setup_logger

logger = logging.getLogger("cascade")


def _create_provider(tier_config: TierConfig, config: CascadeConfig) -> BaseProvider:
    """Factory: create the right provider for a tier config."""
    provider_name = tier_config.provider.lower()

    if provider_name == "anthropic":
        from cascade.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            api_key=config.api_keys.anthropic,
            model=tier_config.model,
        )
    elif provider_name == "openai":
        from cascade.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=config.api_keys.openai,
            model=tier_config.model,
        )
    elif provider_name == "google":
        from cascade.providers.google_provider import GoogleProvider

        return GoogleProvider(
            api_key=config.api_keys.google,
            model=tier_config.model,
        )
    elif provider_name == "ollama":
        from cascade.providers.ollama_provider import OllamaProvider

        return OllamaProvider(
            model=tier_config.model,
            base_url=config.ollama.base_url,
        )
    else:
        raise ValueError(f"Unknown provider: {provider_name}")


def _create_tool_registry(project_root: str) -> ToolRegistry:
    """Create and populate the tool registry."""
    registry = ToolRegistry()

    # File operations
    registry.register(ReadFileTool(project_root))
    registry.register(WriteFileTool(project_root))
    registry.register(EditFileTool(project_root))
    registry.register(ListDirectoryTool(project_root))

    # Shell
    registry.register(RunCommandTool(project_root))

    # Code search
    registry.register(GrepSearchTool(project_root))
    registry.register(FindFilesTool(project_root))

    # Git
    registry.register(GitStatusTool(project_root))
    registry.register(GitDiffTool(project_root))
    registry.register(GitLogTool(project_root))
    registry.register(GitCommitTool(project_root))

    # Web
    registry.register(FetchURLTool())
    registry.register(WebSearchTool())

    return registry


class Cascade:
    """
    Main entry point for the Cascade multi-tier AI agent system.

    Usage:
        from cascade import Cascade

        agent = Cascade(config_path="./cascade.yaml")
        result = agent.run("add error handling to auth.py")
        print(result.summary)
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        config: Optional[CascadeConfig] = None,
        project_root: Optional[str] = None,
    ):
        self.config = config or load_config(config_path)

        # Resolve project root
        if project_root:
            self.project_root = str(Path(project_root).resolve())
        else:
            self.project_root = str(Path(self.config.project_root).resolve())

        # Setup logging
        self.logger = setup_logger(
            verbose=self.config.verbose,
            log_file=self.config.log_file,
        )

        # Create tool registry
        self.tool_registry = _create_tool_registry(self.project_root)

        # Create escalation policy
        self.escalation_policy = EscalationPolicy(self.config.escalation)

        # Create cost tracker
        self.cost_tracker = CostTracker(self.config.budget)

        # Create providers (lazy — only instantiated when needed)
        self._providers: dict[str, BaseProvider] = {}

        # Callbacks for display
        self.on_plan: Optional[Callable] = None
        self.on_tier_start: Optional[Callable] = None
        self.on_tool_call: Optional[Callable] = None
        self.on_tool_result: Optional[Callable] = None
        self.on_thinking: Optional[Callable] = None
        self.on_escalation: Optional[Callable] = None
        self.on_validation: Optional[Callable] = None

    def _track_cost(self, tier: str, amount: float) -> None:
        """Callback for tiers to report their costs."""
        self.cost_tracker.add_cost(tier, amount)

    def _get_provider(self, tier: str) -> BaseProvider:
        """Get or create the provider for a tier."""
        if tier not in self._providers:
            tier_config_map = {
                "t1": self.config.tiers.t1_orchestrator,
                "t2": self.config.tiers.t2_worker,
                "t3": self.config.tiers.t3_executor,
            }
            tier_config = tier_config_map[tier]
            self._providers[tier] = _create_provider(tier_config, self.config)
        return self._providers[tier]

    def _create_orchestrator(self) -> Orchestrator:
        return Orchestrator(
            provider=self._get_provider("t1"),
            tool_registry=self.tool_registry,
            escalation_policy=self.escalation_policy,
        )

    def _create_worker(self) -> Worker:
        return Worker(
            provider=self._get_provider("t2"),
            tool_registry=self.tool_registry,
            escalation_policy=self.escalation_policy,
            cost_callback=self._track_cost,
        )

    def _create_executor(self) -> Executor:
        return Executor(
            provider=self._get_provider("t3"),
            tool_registry=self.tool_registry,
            escalation_policy=self.escalation_policy,
            cost_callback=self._track_cost,
        )

    def run(self, task_description: str) -> TaskResult:
        """
        Execute a task synchronously.

        Args:
            task_description: Natural language description of the task.

        Returns:
            TaskResult with success status, summary, and cost breakdown.
        """
        return asyncio.run(self.run_async(task_description))

    async def run_async(self, task_description: str) -> TaskResult:
        """Execute a task asynchronously."""
        task = Task(
            id=str(uuid.uuid4())[:8],
            description=task_description,
        )

        logger.info(f"Starting task: {task_description}")

        # ── Step 1: T1 decomposes the task ──────────────────────────
        orchestrator = self._create_orchestrator()

        # Gather project context
        project_context = await self._gather_project_context()

        plan = await orchestrator.decompose_task(task_description, project_context)
        # Track T1 decomposition cost
        t1_prov = self._get_provider("t1")
        if hasattr(t1_prov, '_last_usage') and t1_prov._last_usage:
            self._track_cost("t1", t1_prov.get_cost(t1_prov._last_usage))
        task.plan = plan

        if self.on_plan:
            await self.on_plan(plan)

        logger.info(f"Plan created: {len(plan.subtasks)} subtasks")

        # ── Step 2: Execute subtasks ────────────────────────────────
        worker = self._create_worker()
        executor = self._create_executor()
        subtask_results: list[dict[str, Any]] = []

        while not plan.is_complete():
            subtask = plan.get_next_subtask()
            if subtask is None:
                # All remaining subtasks have unmet dependencies or are done
                pending = [s for s in plan.subtasks if s.status == TaskStatus.PENDING]
                if pending:
                    # Force-fail remaining tasks with unresolvable deps
                    for s in pending:
                        s.mark_failed("Unresolvable dependency")
                break

            subtask.mark_in_progress()

            if self.on_tier_start:
                await self.on_tier_start(subtask.assigned_tier.value, subtask.description)

            # Build context from completed dependencies
            dep_context = self._build_subtask_context(subtask, plan)

            # Execute based on assigned tier
            success, result_text, confidence = await self._execute_subtask(
                subtask, worker, executor, orchestrator, extra_context=dep_context
            )

            if success:
                subtask.mark_completed(result_text)
            elif subtask.status == TaskStatus.ESCALATED:
                # Already handled by _execute_subtask — if it still failed after
                # escalation, mark as failed so dependents can see
                if not success:
                    subtask.mark_failed(result_text)
            else:
                subtask.mark_failed(result_text)

            subtask_results.append(
                {
                    "id": subtask.id,
                    "description": subtask.description,
                    "tier": subtask.assigned_tier.value,
                    "status": subtask.status.value,
                    "result": result_text[:500],
                    "confidence": confidence,
                }
            )

        # ── Step 3: Compile results ─────────────────────────────────
        all_success = all(
            st.status == TaskStatus.COMPLETED for st in plan.subtasks
        )

        summaries = []
        for st in plan.subtasks:
            if st.status == TaskStatus.COMPLETED and st.result:
                summaries.append(st.result)

        return TaskResult(
            success=all_success,
            summary="\n\n".join(summaries) if summaries else "No results produced.",
            details=plan.reasoning,
            subtask_results=subtask_results,
            total_cost=self.cost_tracker.total_cost,
            tier_costs=dict(self.cost_tracker.costs),
        )

    async def _execute_subtask(
        self,
        subtask: SubTask,
        worker: Worker,
        executor: Executor,
        orchestrator: Orchestrator,
        extra_context: str = "",
    ) -> tuple[bool, str, float]:
        """Execute a subtask with automatic chained escalation (T3→T2→T1)."""
        context = extra_context

        # Callbacks for display
        async def tool_call_cb(name: str, args: dict) -> None:
            if self.on_tool_call:
                await self.on_tool_call(name, args)

        async def thinking_cb(text: str) -> None:
            if self.on_thinking:
                await self.on_thinking(text)

        # Escalation chain: try current tier, escalate upward as needed
        tier_order = ["t3", "t2", "t1"]
        current_tier = subtask.assigned_tier.value
        start_idx = tier_order.index(current_tier) if current_tier in tier_order else 1

        for tier_idx in range(start_idx, len(tier_order)):
            current_tier = tier_order[tier_idx]

            if current_tier == "t3":
                success, result, confidence = await executor.execute_subtask(
                    subtask, context, on_tool_call=tool_call_cb, on_thinking=thinking_cb
                )
            elif current_tier == "t2":
                success, result, confidence = await worker.execute_subtask(
                    subtask, context, on_tool_call=tool_call_cb, on_thinking=thinking_cb
                )
            else:  # t1 — orchestrator handles directly
                try:
                    esc_context = self.escalation_policy.build_context(
                        from_tier="t2",
                        reason=result if 'result' in dir() else "Escalated to T1",
                        task_description=subtask.description,
                        attempts=subtask.retries,
                        errors=[subtask.error] if subtask.error else [],
                    )
                    guidance = await orchestrator.handle_escalation(esc_context)

                    if guidance.get("action") == "resolve":
                        return True, guidance.get("resolution", "Resolved by T1"), 0.9
                    elif guidance.get("action") == "retry":
                        subtask.status = TaskStatus.IN_PROGRESS
                        instructions = guidance.get("instructions", "")
                        if self.on_tier_start:
                            await self.on_tier_start("t2", f"(retry) {subtask.description}")
                        success, result, confidence = await worker.execute_with_instructions(
                            instructions, subtask,
                            on_tool_call=tool_call_cb, on_thinking=thinking_cb,
                        )
                        return success, result, confidence
                    else:
                        return False, guidance.get("resolution", "T1 could not resolve"), 0.3
                except Exception as e:
                    return False, f"T1 escalation failed: {e}", 0.1

            # If successful, we're done
            if success:
                return success, result, confidence

            # If the tier escalated (not just failed), chain to next tier
            if subtask.status == TaskStatus.ESCALATED:
                next_tier = tier_order[tier_idx + 1] if tier_idx + 1 < len(tier_order) else None
                if next_tier:
                    if self.on_escalation:
                        await self.on_escalation(current_tier, next_tier, result)

                    # Reset subtask for the next tier
                    subtask.status = TaskStatus.IN_PROGRESS
                    subtask.assigned_tier = TierAssignment(next_tier)
                    context += f"\n\nEscalated from {current_tier.upper()}: {result}"

                    if self.on_tier_start:
                        await self.on_tier_start(next_tier, subtask.description)

                    continue  # Try next tier
                else:
                    # No higher tier to escalate to
                    return False, result, confidence
            else:
                # Failed without escalating — just return failure
                return False, result, confidence

        return False, result if 'result' in dir() else "All tiers exhausted", 0.1

    def _build_subtask_context(self, subtask: SubTask, plan: TaskPlan) -> str:
        """Build context from completed dependency results."""
        if not subtask.dependencies or not plan:
            return ""

        context_parts: list[str] = []
        for dep_id in subtask.dependencies:
            for st in plan.subtasks:
                if st.id == dep_id and st.status == TaskStatus.COMPLETED and st.result:
                    context_parts.append(
                        f"### Result from '{st.description}':\n{st.result[:2000]}"
                    )
                    break

        if context_parts:
            return "## Context from previous subtasks\n\n" + "\n\n".join(context_parts)
        return ""

    async def _gather_project_context(self) -> str:
        """Gather basic project context for the orchestrator."""
        from cascade.tools.base import Tier

        # List project root
        result = await self.tool_registry.execute(
            "list_directory",
            Tier.T1,
            path=self.project_root,
            max_depth=2,
        )
        context = f"Project directory ({self.project_root}):\n{result.output}"
        return context

    async def list_models(self) -> dict[str, list[str]]:
        """List available models for each configured provider."""
        models: dict[str, list[str]] = {}

        for tier_name in ["t1", "t2", "t3"]:
            try:
                provider = self._get_provider(tier_name)
                tier_models = await provider.list_models()
                provider_name = getattr(provider, "__class__", type(provider)).__name__
                models[f"{tier_name} ({provider_name})"] = tier_models
            except Exception as e:
                models[tier_name] = [f"Error: {e}"]

        return models
