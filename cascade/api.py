"""Cascade public API and runtime composition root."""

from __future__ import annotations

import asyncio
import inspect
import logging
import warnings
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

from cascade.budget.tracker import CostTracker
from cascade.config import CascadeConfig, ModelConfig, load_config
from cascade.core.approval import ApprovalHandler
from cascade.core.escalation import EscalationPolicy
from cascade.core.events import EventBus
from cascade.core.runtime import ExecutionContext, ExecutionEvent, PlanPreview
from cascade.core.task import TaskResult
from cascade.observability.rollback import RollbackManager
from cascade.observability.tracing import load_trace
from cascade.plugins.registry import PluginRegistry
from cascade.providers.base import BaseProvider
from cascade.providers.benchmark import ModelBenchmarker
from cascade.providers.router import ProviderRouter
from cascade.strategy.base import PlannerStrategy
from cascade.strategy.default import DefaultPlannerStrategy
from cascade.tools.base import BaseTool, ToolRegistry
from cascade.tools.code_search import GrepSearchTool
from cascade.tools.diff_preview import DiffPreviewTool
from cascade.tools.file_ops import (
    ApplyPatchTool,
    DeletePathTool,
    EditFileTool,
    FindFilesTool,
    GlobFilesTool,
    ListDirectoryTool,
    MovePathTool,
    ReadFileTool,
    ReadFilesTool,
    SearchReplaceTool,
    WriteFileTool,
)
from cascade.tools.git_ops import (
    GitAddTool,
    GitCheckoutTool,
    GitCommitTool,
    GitDiffTool,
    GitLogTool,
    GitShowTool,
    GitStatusTool,
)
from cascade.tools.semantic import SemanticCodeSearchTool
from cascade.tools.shell import (
    ProcessManager,
    ReadProcessOutputTool,
    RunCommandTool,
    StartProcessTool,
    StopProcessTool,
    WriteProcessInputTool,
)
from cascade.tools.web import FetchURLTool, WebSearchTool
from cascade.utils.logger import setup_logger

warnings.filterwarnings("ignore", category=ResourceWarning)

logger = logging.getLogger("cascade")

ROOT_DISCOVERY_TOOLS = [
    "list_directory",
    "read_file",
    "read_files",
    "find_files",
    "glob_files",
    "grep_search",
    "semantic_code_search",
    "git_status",
    "git_diff",
    "git_log",
    "git_show",
]


def _create_raw_provider(model_config: ModelConfig, config: CascadeConfig) -> BaseProvider:
    """Create a concrete provider instance for a model definition."""
    provider_name = model_config.provider.lower()

    if provider_name == "anthropic":
        from cascade.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            api_key=config.api_keys.anthropic,
            model=model_config.model,
        )
    if provider_name == "openai":
        from cascade.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=config.api_keys.openai,
            model=model_config.model,
        )
    if provider_name == "google":
        from cascade.providers.google_provider import GoogleProvider

        return GoogleProvider(
            api_key=config.api_keys.google,
            model=model_config.model,
        )
    if provider_name == "ollama":
        from cascade.providers.ollama_provider import OllamaProvider

        return OllamaProvider(
            model=model_config.model,
            base_url=config.ollama.base_url,
        )
    if provider_name == "azure":
        from cascade.providers.azure_provider import create_azure_provider

        endpoint_name = model_config.azure_endpoint
        endpoint = next(
            (ep for ep in config.azure_endpoints if ep.name == endpoint_name),
            None,
        )
        if endpoint is None:
            raise ValueError(
                f"Azure endpoint '{endpoint_name}' not found in azure_endpoints config. "
                "Add it under the azure_endpoints: key in cascade.yaml."
            )
        return create_azure_provider(
            api_key=endpoint.api_key,
            base_url=endpoint.base_url,
            api_version=endpoint.api_version,
            deployment_name=endpoint.deployment_name,
            model=model_config.model,
        )

    raise ValueError(f"Unknown provider: {provider_name}")


def _build_plugin_tool(factory: Any, project_root: str) -> BaseTool:
    """Instantiate a plugin-defined tool with light convention-based wiring."""
    if isinstance(factory, BaseTool):
        return factory
    if inspect.isclass(factory):
        try:
            return factory(project_root=project_root)
        except TypeError:
            return factory(project_root)
    if callable(factory):
        try:
            tool = factory(project_root=project_root)
        except TypeError:
            tool = factory(project_root)
        if isinstance(tool, BaseTool):
            return tool
    raise TypeError("Plugin tool factories must return a BaseTool instance.")


def _create_tool_registry(
    project_root: str,
    config: CascadeConfig,
    plugin_registry: PluginRegistry | None = None,
) -> ToolRegistry:
    """Create and populate the tool registry."""
    registry = ToolRegistry()
    process_manager = ProcessManager(project_root)

    registry.register(ReadFileTool(project_root))
    registry.register(ReadFilesTool(project_root))
    registry.register(WriteFileTool(project_root))
    registry.register(EditFileTool(project_root))
    registry.register(SearchReplaceTool(project_root))
    registry.register(ApplyPatchTool(project_root))
    registry.register(MovePathTool(project_root))
    registry.register(DeletePathTool(project_root))
    registry.register(ListDirectoryTool(project_root))
    registry.register(GlobFilesTool(project_root))
    registry.register(FindFilesTool(project_root))

    registry.register(RunCommandTool(project_root))
    registry.register(StartProcessTool(project_root, process_manager))
    registry.register(ReadProcessOutputTool(process_manager))
    registry.register(WriteProcessInputTool(process_manager))
    registry.register(StopProcessTool(process_manager))

    registry.register(GrepSearchTool(project_root))
    registry.register(DiffPreviewTool(project_root))
    if config.semantic_search.enabled:
        registry.register(
            SemanticCodeSearchTool(
                project_root=project_root,
                base_url=config.semantic_search.base_url,
                embedding_model=config.semantic_search.ollama_embedding_model,
            )
        )

    registry.register(GitStatusTool(project_root))
    registry.register(GitDiffTool(project_root))
    registry.register(GitLogTool(project_root))
    registry.register(GitShowTool(project_root))
    registry.register(GitAddTool(project_root))
    registry.register(GitCommitTool(project_root))
    registry.register(GitCheckoutTool(project_root))

    registry.register(FetchURLTool())
    registry.register(WebSearchTool())

    if plugin_registry and config.plugins.auto_load:
        for package in config.plugins.enabled_packages:
            logger.debug("Plugin package enabled: %s", package)
        try:
            for _name, factory in plugin_registry.load_entry_points("cascade.tools").items():
                registry.register(_build_plugin_tool(factory, project_root))
        except Exception as error:  # pragma: no cover - depends on local env
            logger.warning("Failed loading plugin tools: %s", error)

    return registry


class Cascade:
    """Main entry point for the Cascade multi-tier AI agent system."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        config: Optional[CascadeConfig] = None,
        project_root: Optional[str] = None,
        approval_callback: ApprovalHandler | None = None,
    ):
        self.config = config or load_config(config_path)
        self.project_root = str(Path(project_root or self.config.project_root).resolve())
        self.logger = setup_logger(
            verbose=self.config.verbose,
            log_file=self.config.log_file,
        )

        self.event_bus = EventBus()
        self.plugin_registry = PluginRegistry(self.config.plugins.registry_path)
        self.tool_registry = _create_tool_registry(
            self.project_root,
            self.config,
            plugin_registry=self.plugin_registry,
        )
        self.root_discovery_tools = list(ROOT_DISCOVERY_TOOLS)
        self.escalation_policy = EscalationPolicy(self.config.escalation)
        self.cost_tracker = CostTracker(self.config.budget, self.config)
        self.rollback_manager = RollbackManager(self.project_root)

        self._raw_providers: dict[str, BaseProvider] = {}
        self._providers = self._raw_providers
        self._strategies: dict[str, PlannerStrategy] = {"default": DefaultPlannerStrategy()}
        self._load_plugin_strategies()

        self.on_plan: Optional[Callable[..., Any]] = None
        self.on_tier_start: Optional[Callable[..., Any]] = None
        self.on_tool_call: Optional[Callable[..., Any]] = None
        self.on_tool_result: Optional[Callable[..., Any]] = None
        self.on_thinking: Optional[Callable[..., Any]] = None
        self.on_auditor_block: Optional[Callable[..., Any]] = None
        self.on_escalation: Optional[Callable[..., Any]] = None
        self.on_validation: Optional[Callable[..., Any]] = None
        self.on_approval_request: Optional[ApprovalHandler] = approval_callback

    def _load_plugin_strategies(self) -> None:
        """Load any strategy plugins registered through entry points."""
        if not self.config.plugins.auto_load:
            return
        try:
            for name, factory in self.plugin_registry.load_entry_points("cascade.strategies").items():
                strategy = factory() if inspect.isclass(factory) else factory()
                if isinstance(strategy, PlannerStrategy):
                    self._strategies[name] = strategy
        except Exception as error:  # pragma: no cover - depends on local env
            logger.warning("Failed loading plugin strategies: %s", error)

    def _track_cost(
        self,
        model_id: str,
        amount: float,
        *,
        subtask_id: str = "",
        tier: str = "",
        provider: str = "",
        task_id: str = "",
    ) -> None:
        """Callback for agents to report their costs."""
        self.cost_tracker.add_cost(
            model_id,
            amount,
            subtask_id=subtask_id,
            tier=tier,
            provider=provider,
            task_id=task_id,
        )

    def _get_raw_provider(self, model_id: str) -> BaseProvider:
        """Get or create the concrete provider for a model definition."""
        if model_id in self._raw_providers:
            return self._raw_providers[model_id]

        model_config = self.config.get_model(model_id)
        try:
            provider = _create_raw_provider(model_config, self.config)
        except ValueError:
            loaded = self.plugin_registry.load_entry_points("cascade.providers")
            factory = loaded.get(model_config.provider)
            if factory is None:
                raise
            provider = factory(model_config=model_config, config=self.config)
        self._raw_providers[model_id] = provider
        return provider

    def _get_provider(
        self,
        model_id: str,
        execution_context: ExecutionContext | None = None,
    ) -> BaseProvider:
        """Build a routed provider wrapper for a model id."""
        return ProviderRouter(
            model_id=model_id,
            config=self.config,
            provider_factory=self._get_raw_provider,
            event_bus=self.event_bus,
            execution_context=execution_context,
        )

    def _get_strategy(self) -> PlannerStrategy:
        """Resolve the configured planner strategy."""
        strategy_name = self.config.plugins.strategy or "default"
        strategy = self._strategies.get(strategy_name)
        if strategy is None:
            raise ValueError(f"Planner strategy '{strategy_name}' is not registered.")
        return strategy

    def run(self, task_description: str) -> TaskResult:
        """Execute a task synchronously."""
        return asyncio.run(self.run_async(task_description))

    async def run_async(self, task_description: str) -> TaskResult:
        """Execute a task asynchronously through the configured strategy."""
        return await self._get_strategy().execute(self, task_description)

    async def explain(self, task_description: str) -> PlanPreview:
        """Return a dry-run plan preview for a task."""
        return await self._get_strategy().explain(self, task_description)

    async def run_stream(self, task_description: str) -> AsyncIterator[ExecutionEvent]:
        """Execute a task while yielding live execution events."""
        queue: asyncio.Queue[ExecutionEvent] = asyncio.Queue()

        async def _subscriber(event: ExecutionEvent) -> None:
            await queue.put(event)

        unsubscribe = self.event_bus.subscribe(_subscriber)
        runner = asyncio.create_task(self.run_async(task_description))

        try:
            while True:
                if runner.done() and queue.empty():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield event
                except asyncio.TimeoutError:
                    continue
            await runner
        finally:
            unsubscribe()

    def budget_summary(self) -> dict[str, object]:
        """Return a structured budget summary for the current session."""
        return self.cost_tracker.budget_summary()

    def trace(self, task_id: str) -> dict[str, Any]:
        """Load a persisted task trace."""
        return load_trace(task_id, self.config.observability.trace_dir)

    def rollback(self, task_id: str) -> list[str]:
        """Rollback task changes using recorded file snapshots."""
        task_dir = Path(self.config.observability.trace_dir) / task_id
        return self.rollback_manager.restore(str(task_dir))

    async def benchmark(self) -> dict[str, Any]:
        """Run the built-in provider benchmark suite."""
        benchmarker = ModelBenchmarker()
        results: dict[str, Any] = {}
        for model_config in self.config.models:
            provider = self._get_provider(model_config.id)
            results[model_config.id] = await benchmarker.benchmark_model(
                model_id=model_config.id,
                provider=provider,
            )
        return results

    async def list_models(self) -> dict[str, list[str]]:
        """List available models for each configured provider in the pool."""
        models: dict[str, list[str]] = {}
        for model_cfg in self.config.models:
            try:
                provider = self._get_raw_provider(model_cfg.id)
                provider_models = await provider.list_models()
                models[f"{model_cfg.id} ({model_cfg.provider})"] = provider_models
            except Exception as error:
                models[model_cfg.id] = [f"Error: {error}"]
        return models
