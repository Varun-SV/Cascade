"""Configuration management for Cascade."""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any, Optional

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field, field_validator

from cascade.core.approval import ApprovalMode


class ModelConfig(BaseModel):
    """Configuration for a single model in the pool."""

    id: str
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    temperature: float = 0.2
    max_tokens: int = 4096
    context_window: Optional[int] = None
    fallback_models: list[str] = Field(default_factory=list)
    benchmark_tags: list[str] = Field(default_factory=list)
    # For provider="azure": references an entry in CascadeConfig.azure_endpoints by name
    azure_endpoint: Optional[str] = None


class APIKeysConfig(BaseModel):
    """API key configuration."""

    anthropic: str = ""
    openai: str = ""
    google: str = ""


class OllamaConfig(BaseModel):
    """Ollama-specific settings."""

    base_url: str = "http://localhost:11434"


class AzureEndpointConfig(BaseModel):
    """A single Azure OpenAI endpoint (one resource can have many deployments)."""

    name: str
    base_url: str
    api_key: str = ""
    api_version: str = "2024-02-01"
    deployment_name: str = ""


class EscalationConfig(BaseModel):
    """Escalation thresholds (bubbles up per recursive call)."""

    confidence_threshold: float = 0.5
    max_retries: int = 2


class BudgetConfig(BaseModel):
    """Optional cost budget configuration."""

    enabled: bool = False
    session_max_cost: Optional[float] = None
    task_max_cost: Optional[float] = None
    ledger_path: str = "~/.cascade/state.db"
    estimation_enabled: bool = True
    estimation_warn_threshold: float = 1.0
    tier_max_costs: dict[str, float] = Field(default_factory=dict)
    model_max_cost: dict[str, float] = Field(default_factory=dict)


class ApprovalsConfig(BaseModel):
    """Approval controls for guarded tool execution."""

    mode: ApprovalMode = ApprovalMode.GUARDED
    allowed_command_prefixes: list[list[str]] = Field(default_factory=list)

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: Any) -> str:
        if value == "power_user":
            return "auto"
        return str(value)

    @field_validator("allowed_command_prefixes", mode="before")
    @classmethod
    def _normalize_prefixes(cls, value: Any) -> list[list[str]]:
        if value in (None, ""):
            return []

        normalized: list[list[str]] = []
        for item in value:
            if isinstance(item, str):
                tokens = shlex.split(item)
            else:
                tokens = [str(part) for part in item]
            if tokens:
                normalized.append(tokens)
        return normalized


class CascadeConfig(BaseModel):
    """Root configuration for Cascade."""

    models: list[ModelConfig] = Field(
        default_factory=lambda: [
            ModelConfig(
                id="planner",
                provider="anthropic",
                model="claude-sonnet-4-20250514",
                temperature=0.3,
                max_tokens=8192,
            ),
            ModelConfig(
                id="worker",
                provider="anthropic",
                model="claude-sonnet-4-20250514",
                temperature=0.2,
                max_tokens=4096,
            ),
            ModelConfig(
                id="local",
                provider="ollama",
                model="qwen2.5-coder:7b",
                temperature=0.1,
                max_tokens=2048,
            ),
        ]
    )
    default_planner: str = "planner"
    default_auditor: Optional[str] = None
    auditor_enabled: bool = True
    
    api_keys: APIKeysConfig = Field(default_factory=APIKeysConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    azure_endpoints: list[AzureEndpointConfig] = Field(default_factory=list)
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    approvals: ApprovalsConfig = Field(default_factory=ApprovalsConfig)
    runtime: "RuntimeConfig" = Field(default_factory=lambda: RuntimeConfig())
    observability: "ObservabilityConfig" = Field(default_factory=lambda: ObservabilityConfig())
    plugins: "PluginConfig" = Field(default_factory=lambda: PluginConfig())
    semantic_search: "SemanticSearchConfig" = Field(default_factory=lambda: SemanticSearchConfig())
    project_root: str = "."
    verbose: bool = False
    log_file: Optional[str] = None

    def get_model(self, model_id: str) -> ModelConfig:
        """Find a model configuration by ID."""
        for m in self.models:
            if m.id == model_id:
                return m
        raise ValueError(f"Model ID '{model_id}' not found in configuration.")


def _resolve_api_key(config_value: str, env_var: str) -> str:
    """Resolve an API key from config or environment variable."""
    if config_value:
        return config_value
    return os.environ.get(env_var, "")


class RuntimeConfig(BaseModel):
    """Runtime behavior for retries, reflection, and streaming."""

    max_reflections: int = 3
    stream_events: bool = True
    preflight_confirmation: bool = True
    retry_reflection_enabled: bool = True


class ObservabilityConfig(BaseModel):
    """Trace, journal, and telemetry settings."""

    trace_dir: str = ".cascade/traces"
    journal_path: str = ".cascade/journal.log"
    otel_enabled: bool = False
    otel_exporter: str = ""


class PluginConfig(BaseModel):
    """Plugin loading and strategy selection."""

    registry_path: str = "~/.cascade/plugins.json"
    enabled_packages: list[str] = Field(default_factory=list)
    auto_load: bool = True
    strategy: str = "default"


class SemanticSearchConfig(BaseModel):
    """Semantic search backend settings."""

    enabled: bool = True
    ollama_embedding_model: str = "nomic-embed-text"
    base_url: str = "http://localhost:11434"


def load_config(config_path: Optional[str] = None) -> CascadeConfig:
    """
    Load configuration from YAML file.

    Search order:
    1. Explicit path (if provided)
    2. ./cascade.yaml (project-local)
    3. ~/.cascade/config.yaml (global)
    4. Defaults
    """
    config_data: dict[str, Any] = {}

    if config_path:
        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                config_data = yaml.safe_load(f) or {}
    else:
        # Search order: local → global
        search_paths = [
            Path.cwd() / "cascade.yaml",
            Path.home() / ".cascade" / "config.yaml",
        ]
        for path in search_paths:
            if path.exists():
                with open(path) as f:
                    config_data = yaml.safe_load(f) or {}
                break

    config = CascadeConfig(**config_data) if config_data else CascadeConfig()

    # Resolve API keys from environment variables
    config.api_keys.anthropic = _resolve_api_key(
        config.api_keys.anthropic, "CASCADE_ANTHROPIC_API_KEY"
    )
    config.api_keys.openai = _resolve_api_key(
        config.api_keys.openai, "CASCADE_OPENAI_API_KEY"
    )
    config.api_keys.google = _resolve_api_key(
        config.api_keys.google, "CASCADE_GOOGLE_API_KEY"
    )

    # Resolve Azure endpoint API keys from environment variables
    for ep in config.azure_endpoints:
        env_var = f"CASCADE_AZURE_{ep.name.upper().replace('-', '_')}_API_KEY"
        ep.api_key = _resolve_api_key(ep.api_key, env_var)

    return config
