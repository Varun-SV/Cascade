"""Tests for plugin registry helpers and new tooling modules."""

from __future__ import annotations

from cascade.plugins.registry import PluginRegistry
from cascade.tools.diff_preview import DiffPreviewTool
from cascade.tools.semantic import SemanticCodeSearchTool


def test_plugin_registry_round_trips_metadata(tmp_path):
    registry = PluginRegistry(str(tmp_path / "plugins.json"))
    registry.save({"installed": ["demo-plugin"]})

    assert registry.load()["installed"] == ["demo-plugin"]
    assert registry.list_plugins() == ["demo-plugin"]


async def test_semantic_code_search_uses_lexical_fallback(tmp_path, monkeypatch):
    source = tmp_path / "module.py"
    source.write_text(
        "def add_numbers(a, b):\n    return a + b\n\nclass Counter:\n    pass\n",
        encoding="utf-8",
    )
    tool = SemanticCodeSearchTool(project_root=str(tmp_path))

    async def _no_embeddings(_text: str) -> list[float]:
        return []

    monkeypatch.setattr(tool, "_embed_text", _no_embeddings)

    result = await tool.execute(query="add numbers")

    assert result.success
    assert "add_numbers" in result.output


async def test_diff_preview_stages_patch(tmp_path):
    tool = DiffPreviewTool(str(tmp_path))
    patch = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n"

    result = await tool.execute(patch=patch, stage_name="example.diff")

    assert result.success
    assert (tmp_path / "pending_changes" / "example.diff").exists()
