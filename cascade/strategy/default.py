"""Default planner strategy for Cascade task execution and explain flows."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from cascade.core.agent import CascadeAgent
from cascade.core.runtime import ExecutionContext, ExecutionEvent, EventLevel, PlanPreview, PlanStep
from cascade.core.task import SubTask, Task, TaskResult
from cascade.observability.journal import ActionJournal
from cascade.observability.rollback import RollbackManager
from cascade.observability.tracing import TaskTraceWriter
from cascade.providers.base import Message, Role
from cascade.strategy.base import PlannerStrategy

if TYPE_CHECKING:
    from cascade.api import Cascade


class DefaultPlannerStrategy(PlannerStrategy):
    """Use the recursive CascadeAgent runtime as the default execution strategy."""

    async def explain(self, cascade: "Cascade", task_description: str) -> PlanPreview:
        repo_snapshot = []
        for tool_name, kwargs in [
            ("list_directory", {"path": ".", "max_depth": 2}),
            ("git_status", {}),
        ]:
            if cascade.tool_registry.get(tool_name):
                result = await cascade.tool_registry.execute(
                    tool_name,
                    ["all"],
                    **kwargs,
                )
                if result.success and result.output:
                    repo_snapshot.append(f"## {tool_name}\n{result.output[:1500]}")

        repo_snapshot_text = "\n\n".join(repo_snapshot)
        prompt = (
            "You are planning a software engineering task. "
            "Return JSON with keys summary, risks, and steps. "
            "Each step should have title, detail, and tools.\n\n"
            f"Task:\n{task_description}\n\n"
            f"Repo snapshot:\n{repo_snapshot_text}"
        )

        provider = cascade._get_provider(cascade.config.default_planner)
        response = await provider.generate(
            messages=[Message(role=Role.USER, content=prompt)],
            temperature=0.1,
            max_tokens=1024,
        )

        try:
            payload = json.loads(response.content)
            preview = PlanPreview(
                summary=payload.get("summary", task_description),
                steps=[
                    PlanStep(
                        title=step.get("title", f"Step {index + 1}"),
                        detail=step.get("detail", ""),
                        tools=step.get("tools", []),
                        risks=step.get("risks", []),
                    )
                    for index, step in enumerate(payload.get("steps", []))
                ],
                risks=payload.get("risks", []),
                requires_confirmation=True,
                estimated_cost=cascade.cost_tracker.estimate_cost(task_description),
                repo_snapshot=repo_snapshot_text,
            )
            if cascade.on_plan:
                maybe_result = cascade.on_plan(preview)
                if hasattr(maybe_result, "__await__"):
                    await maybe_result
            return preview
        except Exception:
            preview = PlanPreview(
                summary=response.content or task_description,
                steps=[
                    PlanStep(
                        title="Inspect repository",
                        detail="Use discovery tools to understand the repo and clarify the plan.",
                        tools=["list_directory", "find_files", "grep_search"],
                    ),
                    PlanStep(
                        title="Execute changes",
                        detail="Delegate or apply edits using the appropriate tool set.",
                        tools=["delegate_task", "apply_patch", "run_command"],
                    ),
                ],
                risks=["Plan preview fell back to a generic parser due to malformed planner output."],
                requires_confirmation=True,
                estimated_cost=cascade.cost_tracker.estimate_cost(task_description),
                repo_snapshot=repo_snapshot_text,
            )
            if cascade.on_plan:
                maybe_result = cascade.on_plan(preview)
                if hasattr(maybe_result, "__await__"):
                    await maybe_result
            return preview

    async def execute(self, cascade: "Cascade", task_description: str) -> TaskResult:
        task = Task(id=str(uuid.uuid4())[:8], description=task_description)
        cascade.cost_tracker.start_task(task.id, task_description)

        artifacts_root = Path(cascade.config.observability.trace_dir)
        task_artifact_dir = str((artifacts_root / task.id).resolve())
        estimated_cost = cascade.cost_tracker.estimate_cost(task_description)
        context = ExecutionContext(
            task_id=task.id,
            session_id=cascade.cost_tracker.session_id,
            task_description=task_description,
            project_root=cascade.project_root,
            approval_mode=cascade.config.approvals.mode.value,
            planner_model_id=cascade.config.default_planner,
            task_artifact_dir=task_artifact_dir,
            current_agent_id=cascade.config.default_planner,
            current_model_id=cascade.config.default_planner,
        )

        trace_writer = TaskTraceWriter(cascade.config.observability.trace_dir, task.id)
        journal = ActionJournal(cascade.config.observability.journal_path)
        unsubscribe_trace = cascade.event_bus.subscribe(trace_writer)
        unsubscribe_journal = cascade.event_bus.subscribe(journal)
        rollback_manager = RollbackManager(cascade.project_root)

        await cascade.event_bus.emit(
            ExecutionEvent(
                event_type="task.started",
                task_id=task.id,
                session_id=context.session_id,
                agent_id=context.current_agent_id,
                model_id=context.current_model_id,
                level=EventLevel.INFO,
                message="Task execution started.",
                payload={"description": task_description, "estimated_cost": estimated_cost},
            )
        )

        if (
            cascade.config.budget.enabled
            and cascade.config.budget.task_max_cost is not None
            and estimated_cost > cascade.config.budget.task_max_cost
        ):
            await cascade.event_bus.emit(
                ExecutionEvent(
                    event_type="budget.warning",
                    task_id=task.id,
                    session_id=context.session_id,
                    agent_id=context.current_agent_id,
                    model_id=context.current_model_id,
                    level=EventLevel.WARNING,
                    message="Estimated task cost exceeds the configured task budget.",
                    payload={
                        "estimated_cost": estimated_cost,
                        "task_budget": cascade.config.budget.task_max_cost,
                    },
                )
            )

        root_model_id = cascade.config.default_planner
        root_context = context.child(
            agent_id=f"{root_model_id}:{task.id}",
            model_id=root_model_id,
            subtask_id=task.id,
        )
        root_agent = CascadeAgent(
            model_id=root_model_id,
            provider=cascade._get_provider(root_model_id, root_context),
            config=cascade.config,
            tool_registry=cascade.tool_registry,
            escalation_policy=cascade.escalation_policy,
            allowed_tools=cascade.root_discovery_tools,
            provider_factory=cascade._get_provider,
            max_iterations=60,
            cost_callback=cascade._track_cost,
            approval_handler=cascade.on_approval_request,
            event_bus=cascade.event_bus,
            execution_context=root_context,
            rollback_manager=rollback_manager,
        )

        subtask = SubTask(
            id=task.id,
            description=task_description,
            assigned_model=root_model_id,
            assigned_tools=cascade.root_discovery_tools,
        )

        if cascade.on_tier_start:
            await cascade.on_tier_start(root_model_id, "Root Agent Planning & Execution")

        async def handle_agent_spawn(parent_model: str, child_model: str, desc: str) -> None:
            if cascade.on_tier_start:
                await cascade.on_tier_start(child_model, desc)

        try:
            success, result_text, confidence = await root_agent.execute_subtask(
                subtask,
                context="",
                on_tool_call=cascade.on_tool_call,
                on_thinking=cascade.on_thinking,
                on_agent_spawn=handle_agent_spawn,
                on_auditor_block=cascade.on_auditor_block,
                on_tool_result=cascade.on_tool_result,
                on_approval_request=cascade.on_approval_request,
            )

            await cascade.event_bus.emit(
                ExecutionEvent(
                    event_type="task.completed" if success else "task.failed",
                    task_id=task.id,
                    session_id=context.session_id,
                    agent_id=root_context.current_agent_id,
                    model_id=root_model_id,
                    level=EventLevel.INFO if success else EventLevel.ERROR,
                    message=result_text[:500] if result_text else "Task finished.",
                    payload={"confidence": confidence},
                )
            )

            return TaskResult(
                success=success,
                summary=result_text,
                details=f"Master agent completed execution with confidence {confidence:.2f}",
                subtask_results=[
                    {
                        "id": subtask.id,
                        "description": subtask.description,
                        "model": root_model_id,
                        "status": "completed" if success else "failed",
                        "result": result_text[:500],
                        "confidence": confidence,
                    }
                ],
                total_cost=cascade.cost_tracker.total_cost,
                model_costs=dict(cascade.cost_tracker.costs),
            )
        finally:
            trace_writer.finalize()
            unsubscribe_trace()
            unsubscribe_journal()
