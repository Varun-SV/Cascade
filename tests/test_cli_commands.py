"""Tests for CLI JSON-mode command surfaces."""

from __future__ import annotations

from typer.testing import CliRunner

from cascade.cli import app
from cascade.core.runtime import PlanPreview

runner = CliRunner()


def test_version_command_supports_json():
    result = runner.invoke(app, ["version", "--output", "json"])

    assert result.exit_code == 0
    assert '"version"' in result.stdout


def test_init_command_supports_json(tmp_path):
    result = runner.invoke(app, ["init", str(tmp_path), "--output", "json"])

    assert result.exit_code == 0
    assert '"created"' in result.stdout


def test_explain_command_supports_json(monkeypatch):
    class _StubCascade:
        def __init__(self):
            self.config = type("Config", (), {"runtime": type("Runtime", (), {"preflight_confirmation": False})()})()

        async def explain(self, task: str) -> PlanPreview:
            return PlanPreview(summary=f"plan for {task}")

    monkeypatch.setattr("cascade.cli._create_cascade", lambda **_kwargs: _StubCascade())
    result = runner.invoke(app, ["explain", "test task", "--output", "json"])

    assert result.exit_code == 0
    assert '"summary"' in result.stdout
