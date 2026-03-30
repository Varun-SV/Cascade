"""Tests for file and search tools."""

from pathlib import Path

import pytest

from cascade.tools.base import ToolRegistry
from cascade.tools.code_search import GrepSearchTool
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


@pytest.fixture
def project_dir(tmp_path):
    """Create a temporary project directory with test files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def hello():\n    print('hello')\n")
    (tmp_path / "src" / "utils.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "README.md").write_text("# Test Project\nA test project.\n")
    return tmp_path


class TestReadTools:
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
    async def test_read_files(self, project_dir):
        tool = ReadFilesTool(str(project_dir))
        result = await tool.execute(paths=["src/main.py", "README.md"])
        assert result.success
        assert "==> src/main.py <==" in result.output
        assert "==> README.md <==" in result.output


class TestWriteAndEditTools:
    @pytest.mark.asyncio
    async def test_write_new_file(self, project_dir):
        tool = WriteFileTool(str(project_dir))
        result = await tool.execute(path="new_file.py", content="# new file")
        assert result.success
        assert (project_dir / "new_file.py").read_text() == "# new file"

    @pytest.mark.asyncio
    async def test_edit_file(self, project_dir):
        tool = EditFileTool(str(project_dir))
        result = await tool.execute(
            path="src/main.py",
            target="def hello():",
            replacement="def hello(name):",
        )
        assert result.success
        assert "def hello(name):" in (project_dir / "src" / "main.py").read_text()

    @pytest.mark.asyncio
    async def test_search_replace_literal(self, project_dir):
        tool = SearchReplaceTool(str(project_dir))
        result = await tool.execute(
            path="src/main.py",
            search="hello",
            replacement="hola",
            max_replacements=2,
        )
        assert result.success
        content = (project_dir / "src" / "main.py").read_text()
        assert content.count("hola") == 2

    @pytest.mark.asyncio
    async def test_search_replace_regex_occurrence(self, project_dir):
        tool = SearchReplaceTool(str(project_dir))
        result = await tool.execute(
            path="src/utils.py",
            search=r"\b[a-z]\b",
            replacement="value",
            regex=True,
            occurrence=2,
        )
        assert result.success
        assert "def add(a, value):" in (project_dir / "src" / "utils.py").read_text()

    @pytest.mark.asyncio
    async def test_apply_patch_is_atomic(self, project_dir):
        tool = ApplyPatchTool(str(project_dir))
        patch = """--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,2 @@
 def hello():
-    print('hello')
+    print('hola')
--- a/src/utils.py
+++ b/src/utils.py
@@ -1,2 +1,2 @@
-def subtract(a, b):
+def subtract(a, b):
     return a - b
"""
        result = await tool.execute(patch=patch)
        assert not result.success
        assert "hello" in (project_dir / "src" / "main.py").read_text()

    @pytest.mark.asyncio
    async def test_apply_patch_create_and_modify(self, project_dir):
        tool = ApplyPatchTool(str(project_dir))
        patch = """--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,2 @@
 def hello():
-    print('hello')
+    print('hola')
--- /dev/null
+++ b/src/new_module.py
@@ -0,0 +1,2 @@
+def created():
+    return True
"""
        result = await tool.execute(patch=patch)
        assert result.success
        assert "hola" in (project_dir / "src" / "main.py").read_text()
        assert (project_dir / "src" / "new_module.py").exists()

    @pytest.mark.asyncio
    async def test_move_and_delete_path(self, project_dir):
        move_tool = MovePathTool(str(project_dir))
        delete_tool = DeletePathTool(str(project_dir))

        move_result = await move_tool.execute(source="README.md", destination="docs/README.md")
        assert move_result.success
        assert (project_dir / "docs" / "README.md").exists()

        delete_result = await delete_tool.execute(path="docs")
        assert delete_result.success
        assert not (project_dir / "docs").exists()


class TestDirectoryAndSearchTools:
    @pytest.mark.asyncio
    async def test_list_directory(self, project_dir):
        tool = ListDirectoryTool(str(project_dir))
        result = await tool.execute(path=".", max_depth=1)
        assert result.success
        assert "src" in result.output
        assert "README.md" in result.output

    @pytest.mark.asyncio
    async def test_glob_files(self, project_dir):
        tool = GlobFilesTool(str(project_dir))
        result = await tool.execute(pattern="src/*.py")
        assert result.success
        assert "src/main.py" in result.output
        assert "src/utils.py" in result.output

    @pytest.mark.asyncio
    async def test_find_files(self, project_dir):
        tool = FindFilesTool(str(project_dir))
        result = await tool.execute(pattern="*.py")
        assert result.success
        assert "main.py" in result.output
        assert "utils.py" in result.output

    @pytest.mark.asyncio
    async def test_grep_search(self, project_dir):
        tool = GrepSearchTool(str(project_dir))
        result = await tool.execute(query="def hello")
        assert result.success
        assert "main.py" in result.output


class TestToolRegistry:
    def test_register_and_get(self, project_dir):
        registry = ToolRegistry()
        tool = ReadFileTool(str(project_dir))
        registry.register(tool)
        assert registry.get("read_file") is tool

    def test_dynamic_filtering(self, project_dir):
        registry = ToolRegistry()
        registry.register(ReadFileTool(str(project_dir)))
        registry.register(WriteFileTool(str(project_dir)))

        limited_tools = registry.get_tools(["read_file"])
        limited_names = [tool.name for tool in limited_tools]
        assert "read_file" in limited_names
        assert "write_file" not in limited_names

        all_tools = registry.get_tools(["all"])
        all_names = [tool.name for tool in all_tools]
        assert "read_file" in all_names
        assert "write_file" in all_names

    @pytest.mark.asyncio
    async def test_execute_denied(self, project_dir):
        registry = ToolRegistry()
        registry.register(WriteFileTool(str(project_dir)))

        result = await registry.execute(
            "write_file",
            allowed_names=["read_file"],
            path="test.py",
            content="x",
        )
        assert not result.success
        assert "not permitted" in result.error.lower()
