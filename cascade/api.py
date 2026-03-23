"""Cascade — Public Python API for programmatic usage."""

from __future__ import annotations

import asyncio
import logging
import warnings

# Suppress unclosed transport warnings from asyncio/httpx
warnings.filterwarnings("ignore", category=ResourceWarning)

import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from cascade.budget.tracker import CostTracker
from cascade.config import CascadeConfig, ModelConfig, load_config
from cascade.core.agent import CascadeAgent
from cascade.core.escalation import EscalationPolicy
from cascade.core.task import (
    SubTask,
    Task,
    TaskResult,
    TaskStatus,
)
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


def _create_provider(model_config: ModelConfig, config: CascadeConfig) -> BaseProvider:
    """Factory: create the right provider based on model config."""
    provider_name = model_config.provider.lower()

    if provider_name == "anthropic":
        from cascade.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            api_key=config.api_keys.anthropic,
            model=model_config.model,
        )
    elif provider_name == "openai":
        from cascade.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=config.api_keys.openai,
            model=model_config.model,
        )
    elif provider_name == "google":
        from cascade.providers.google_provider import GoogleProvider

        return GoogleProvider(
            api_key=config.api_keys.google,
            model=model_config.model,
        )
    elif provider_name == "ollama":
        from cascade.providers.ollama_provider import OllamaProvider

        return OllamaProvider(
            model=model_config.model,
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
        self.on_plan: Optional[Callable] = None  # Now optional, since plans are dynamic
        self.on_tier_start: Optional[Callable] = None
        self.on_tool_call: Optional[Callable] = None
        self.on_tool_result: Optional[Callable] = None
        self.on_thinking: Optional[Callable] = None
        self.on_auditor_block: Optional[Callable] = None
        self.on_escalation: Optional[Callable] = None
        self.on_validation: Optional[Callable] = None

    def _track_cost(self, model_id: str, amount: float) -> None:
        """Callback for agents to report their costs."""
        self.cost_tracker.add_cost(model_id, amount)

    def _get_provider(self, model_id: str) -> BaseProvider:
        """Get or create the provider for a model definition."""
        if model_id not in self._providers:
            model_config = self.config.get_model(model_id)
            self._providers[model_id] = _create_provider(model_config, self.config)
        return self._providers[model_id]

    def run(self, task_description: str) -> TaskResult:
        """Execute a task synchronously."""
        return asyncio.run(self.run_async(task_description))

    async def run_async(self, task_description: str) -> TaskResult:
        """Execute a task asynchronously through Fractal Agent delegation."""
        task = Task(
            id=str(uuid.uuid4())[:8],
            description=task_description,
        )

        logger.info(f"Starting task: {task_description}")

        # Instantiate root agent
        root_model_id = self.config.default_planner
        
        root_agent = CascadeAgent(
            model_id=root_model_id,
            provider=self._get_provider(root_model_id),
            config=self.config,
            tool_registry=self.tool_registry,
            escalation_policy=self.escalation_policy,
            allowed_tools=["all"],
            provider_factory=self._get_provider,
            max_iterations=60,  # Root agent has higher iterations allowance
            cost_callback=self._track_cost,
        )

        subtask = SubTask(
            id=str(uuid.uuid4())[:8],
            description=task_description,
            assigned_model=root_model_id,
            assigned_tools=["all"],
        )
        
        # We can map the legacy `on_tier_start` callback to when agents spawn
        async def handle_agent_spawn(parent_model: str, child_model: str, desc: str):
            if self.on_tier_start:
                await self.on_tier_start(child_model, desc)

        if self.on_tier_start:
            await self.on_tier_start(root_model_id, "Root Agent Planning & Execution")

        success, result_text, confidence = await root_agent.execute_subtask(
            subtask,
            context="",
            on_tool_call=self.on_tool_call,
            on_thinking=self.on_thinking,
            on_agent_spawn=handle_agent_spawn,
            on_auditor_block=self.on_auditor_block,
            on_tool_result=self.on_tool_result,
        )

        subtask_results = [
            {
                "id": subtask.id,
                "description": subtask.description,
                "model": root_model_id,
                "status": "completed" if success else "failed",
                "result": result_text[:500],
                "confidence": confidence,
            }
        ]

        return TaskResult(
            success=success,
            summary=result_text,
            details=f"Master agent completed execution with confidence {confidence:.2f}",
            subtask_results=subtask_results,
            total_cost=self.cost_tracker.total_cost,
            model_costs=dict(self.cost_tracker.costs),
        )

    async def list_models(self) -> dict[str, list[str]]:
        """List available models for each configured provider in the pool."""
        models: dict[str, list[str]] = {}

        for model_cfg in self.config.models:
            try:
                provider = self._get_provider(model_cfg.id)
                provider_models = await provider.list_models()
                models[f"{model_cfg.id} ({model_cfg.provider})"] = provider_models
            except Exception as e:
                models[model_cfg.id] = [f"Error: {e}"]

        return models
