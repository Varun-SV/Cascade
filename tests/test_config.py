"""Tests for configuration system."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from cascade.config import CascadeConfig, load_config


class TestCascadeConfig:
    """Test configuration loading and defaults."""

    def test_default_config(self):
        """Defaults should produce a valid config."""
        config = CascadeConfig()
        assert config.tiers.t1_orchestrator.provider == "anthropic"
        assert config.tiers.t2_worker.provider == "anthropic"
        assert config.tiers.t3_executor.provider == "ollama"
        assert config.escalation.t3_confidence_threshold == 0.6
        assert config.budget.enabled is False

    def test_load_from_yaml(self, tmp_path):
        """Should load config from a YAML file."""
        config_data = {
            "tiers": {
                "t1_orchestrator": {
                    "provider": "openai",
                    "model": "gpt-4o",
                },
                "t2_worker": {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                },
            },
            "escalation": {
                "t3_confidence_threshold": 0.7,
            },
            "budget": {
                "enabled": True,
                "session_max_cost": 1.00,
            },
        }

        config_file = tmp_path / "cascade.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(str(config_file))
        assert config.tiers.t1_orchestrator.provider == "openai"
        assert config.tiers.t1_orchestrator.model == "gpt-4o"
        assert config.escalation.t3_confidence_threshold == 0.7
        assert config.budget.enabled is True
        assert config.budget.session_max_cost == 1.00

    def test_env_var_override(self, monkeypatch):
        """API keys should be loadable from environment variables."""
        monkeypatch.setenv("CASCADE_ANTHROPIC_API_KEY", "test-key-123")
        config = load_config()  # No file — uses defaults
        assert config.api_keys.anthropic == "test-key-123"

    def test_missing_config_uses_defaults(self):
        """Should return defaults when no config file exists."""
        config = load_config("/nonexistent/path.yaml")
        assert config.tiers.t1_orchestrator.provider == "anthropic"

    def test_tool_permissions_defaults(self):
        """Default tool permissions should be set."""
        config = CascadeConfig()
        assert "read_file" in config.tools.t3_allowed
        assert "run_command" not in config.tools.t3_allowed
        assert "run_command" in config.tools.t2_allowed
        assert config.tools.t1_allowed == "all"
