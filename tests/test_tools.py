"""Tests for the tool system."""

import os
import tempfile
from pathlib import Path

import pytest

from cascade.tools.base import Tier, ToolRegistry, ToolResult
from cascade.tools.code_search import FindFilesTool, GrepSearchTool
from cascade.tools.file_ops import (
    EditFileTool,
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
)


@pytest.fixture
def project_dir(tmp_path):
    """Create a temporary project directory with test files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def hello():\n    print('hello')\n")
    (tmp_path / "src" / "utils.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "README.md").write_text("# Test Project\nA test project.\n")
    return tmp_path


class TestReadFileTool:
    @pytest.mark.asyncio
    async def test_read_file(self, project_dir):
        tool = ReadFileTool(str(project_dir))
        result = await tool.execute(path="src/main.py")
        assert result.success
        assert "def hello" in result.output

    @pytest.mark.asyncio
    async def test_read_file_with_lines(self, project_dir):
        tool = ReadFileTool(str(project_dir))
        result = await tool.execute(path="src/main.py", start_line=1, end_line=1)
        assert result.success
        assert "def hello" in result.output
        assert "print" not in result.output

    @pytest.mark.asyncio
    async def test_read_nonexistent(self, project_dir):
        tool = ReadFileTool(str(project_dir))
        result = await tool.execute(path="nonexistent.py")
        assert not result.success
        assert "not found" in result.error.lower()


class TestWriteFileTool:
    @pytest.mark.asyncio
    async def test_write_new_file(self, project_dir):
        tool = WriteFileTool(str(project_dir))
        result = await tool.execute(path="new_file.py", content="# new file")
        assert result.success
        assert (project_dir / "new_file.py").exists()
        assert (project_dir / "new_file.py").read_text() == "# new file"

    @pytest.mark.asyncio
    async def test_write_creates_dirs(self, project_dir):
        tool = WriteFileTool(str(project_dir))
        result = await tool.execute(path="deep/nested/file.py", content="content")
        assert result.success
        assert (project_dir / "deep" / "nested" / "file.py").exists()


class TestEditFileTool:
    @pytest.mark.asyncio
    async def test_edit_file(self, project_dir):
        tool = EditFileTool(str(project_dir))
        result = await tool.execute(
            path="src/main.py",
            target="def hello():",
            replacement="def hello(name):",
        )
        assert result.success
        content = (project_dir / "src" / "main.py").read_text()
        assert "def hello(name):" in content

    @pytest.mark.asyncio
    async def test_edit_target_not_found(self, project_dir):
        tool = EditFileTool(str(project_dir))
        result = await tool.execute(
            path="src/main.py",
            target="nonexistent text",
            replacement="something",
        )
        assert not result.success
        assert "not found" in result.error.lower()


class TestListDirectoryTool:
    @pytest.mark.asyncio
    async def test_list_directory(self, project_dir):
        tool = ListDirectoryTool(str(project_dir))
        result = await tool.execute(path=".", max_depth=1)
        assert result.success
        assert "src" in result.output
        assert "README.md" in result.output


class TestToolRegistry:
    def test_register_and_get(self, project_dir):
        registry = ToolRegistry()
        tool = ReadFileTool(str(project_dir))
        registry.register(tool)
        assert registry.get("read_file") is tool

    def test_tier_filtering(self, project_dir):
        registry = ToolRegistry()
        registry.register(ReadFileTool(str(project_dir)))  # All tiers
        registry.register(WriteFileTool(str(project_dir)))  # T1, T2 only

        t3_tools = registry.get_tools_for_tier(Tier.T3)
        t2_tools = registry.get_tools_for_tier(Tier.T2)

        t3_names = [t.name for t in t3_tools]
        t2_names = [t.name for t in t2_tools]

        assert "read_file" in t3_names
        assert "write_file" not in t3_names
        assert "read_file" in t2_names
        assert "write_file" in t2_names

    @pytest.mark.asyncio
    async def test_execute_denied(self, project_dir):
        registry = ToolRegistry()
        registry.register(WriteFileTool(str(project_dir)))

        result = await registry.execute("write_file", Tier.T3, path="test.py", content="x")
        assert not result.success
        assert "not allowed" in result.error.lower()


class TestGrepSearchTool:
    @pytest.mark.asyncio
    async def test_grep_search(self, project_dir):
        tool = GrepSearchTool(str(project_dir))
        result = await tool.execute(query="def hello")
        assert result.success
        assert "main.py" in result.output

    @pytest.mark.asyncio
    async def test_grep_no_results(self, project_dir):
        tool = GrepSearchTool(str(project_dir))
        result = await tool.execute(query="nonexistent_function_xyz")
        assert result.success
        assert "no matches" in result.output.lower()


class TestFindFilesTool:
    @pytest.mark.asyncio
    async def test_find_files(self, project_dir):
        tool = FindFilesTool(str(project_dir))
        result = await tool.execute(pattern="*.py")
        assert result.success
        assert "main.py" in result.output
        assert "utils.py" in result.output
