"""Configuration management for Cascade."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


class TierConfig(BaseModel):
    """Configuration for a single model tier."""

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
    """Escalation thresholds."""

    t3_confidence_threshold: float = 0.6
    t2_confidence_threshold: float = 0.5
    max_retries_before_escalation: int = 2


class BudgetConfig(BaseModel):
    """Optional cost budget configuration."""

    enabled: bool = False
    t1_max_cost: Optional[float] = None
    t2_max_cost: Optional[float] = None
    t3_max_cost: Optional[float] = None
    session_max_cost: Optional[float] = None


class TiersConfig(BaseModel):
    """All tier configurations."""

    t1_orchestrator: TierConfig = Field(
        default_factory=lambda: TierConfig(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            temperature=0.3,
            max_tokens=8192,
        )
    )
    t2_worker: TierConfig = Field(
        default_factory=lambda: TierConfig(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            temperature=0.2,
            max_tokens=4096,
        )
    )
    t3_executor: TierConfig = Field(
        default_factory=lambda: TierConfig(
            provider="ollama",
            model="qwen2.5-coder:7b",
            temperature=0.1,
            max_tokens=2048,
        )
    )


class ToolPermissions(BaseModel):
    """Tool access control per tier."""

    t3_allowed: list[str] = Field(
        default_factory=lambda: [
            "read_file",
            "list_directory",
            "grep_search",
            "find_files",
        ]
    )
    t2_allowed: list[str] = Field(
        default_factory=lambda: [
            "read_file",
            "write_file",
            "edit_file",
            "list_directory",
            "run_command",
            "grep_search",
            "find_files",
            "git_status",
            "git_diff",
            "git_log",
            "git_commit",
            "fetch_url",
            "web_search",
        ]
    )
    t1_allowed: Any = "all"


class CascadeConfig(BaseModel):
    """Root configuration for Cascade."""

    tiers: TiersConfig = Field(default_factory=TiersConfig)
    api_keys: APIKeysConfig = Field(default_factory=APIKeysConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    tools: ToolPermissions = Field(default_factory=ToolPermissions)
    project_root: str = "."
    verbose: bool = False
    log_file: Optional[str] = None


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
