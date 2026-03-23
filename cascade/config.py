"""Configuration management for Cascade."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    """Configuration for a single model in the pool."""

    id: str
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    temperature: float = 0.2
    max_tokens: int = 4096


class APIKeysConfig(BaseModel):
    """API key configuration."""

    anthropic: str = ""
    openai: str = ""
    google: str = ""


class OllamaConfig(BaseModel):
    """Ollama-specific settings."""

    base_url: str = "http://localhost:11434"


class EscalationConfig(BaseModel):
    """Escalation thresholds (bubbles up per recursive call)."""

    confidence_threshold: float = 0.5
    max_retries: int = 2


class BudgetConfig(BaseModel):
    """Optional cost budget configuration."""

    enabled: bool = False
    session_max_cost: Optional[float] = None
    model_max_cost: dict[str, float] = Field(default_factory=dict)


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
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
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


def load_config(config_path: Optional[str] = None) -> CascadeConfig:
    """
    Load configuration from YAML file.

    Search order:
    1. Explicit path (if provided)
    2. ./cascade.yaml (project-local)
    3. ~/.cascade/config.yaml (global)
    4. Defaults
    """
    config_data: dict = {}

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

    return config
