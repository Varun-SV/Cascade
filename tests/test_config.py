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
        """Defaults should produce a valid config with models list."""
        config = CascadeConfig()
        assert config.default_planner == "planner"
        assert len(config.models) == 3
        planner = config.get_model("planner")
        assert planner.provider == "anthropic"
        assert config.escalation.confidence_threshold == 0.5
        assert config.budget.enabled is False

    def test_load_from_yaml(self, tmp_path):
        """Should load config from a YAML file."""
        config_data = {
            "default_planner": "worker",
            "models": [
                {
                    "id": "worker",
                    "provider": "openai",
                    "model": "gpt-4o",
                }
            ],
            "escalation": {
                "confidence_threshold": 0.7,
            },
            "budget": {
                "enabled": True,
                "session_max_cost": 1.00,
            },
        }

        config_file = tmp_path / "cascade.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(str(config_file))
        assert config.default_planner == "worker"
        worker = config.get_model("worker")
        assert worker.provider == "openai"
        assert worker.model == "gpt-4o"
        assert config.escalation.confidence_threshold == 0.7
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
        assert config.default_planner == "planner"

    def test_missing_model_raises_error(self):
        """Looking up a nonexistent model should raise ValueError."""
        config = CascadeConfig()
        with pytest.raises(ValueError, match="not found"):
            config.get_model("nonexistent_model_id")
