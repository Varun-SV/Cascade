"""Tests for git tools."""

from __future__ import annotations

import git
import pytest

from cascade.tools.git_ops import (
    GitAddTool,
    GitCheckoutTool,
    GitCommitTool,
    GitDiffTool,
    GitShowTool,
    GitStatusTool,
)


@pytest.fixture
def git_repo_dir(tmp_path):
    repo = git.Repo.init(tmp_path)
    repo.git.config("user.name", "Cascade Test")
    repo.git.config("user.email", "cascade@example.com")

    file_path = tmp_path / "app.py"
    file_path.write_text("print('hello')\n")
    repo.index.add(["app.py"])
    repo.index.commit("initial commit")
    return tmp_path


@pytest.mark.asyncio
async def test_git_show_and_diff(git_repo_dir):
    (git_repo_dir / "app.py").write_text("print('hello world')\n")

    diff_tool = GitDiffTool(str(git_repo_dir))
    diff_result = await diff_tool.execute(path="app.py")
    assert diff_result.success
    assert "hello world" in diff_result.output

    show_tool = GitShowTool(str(git_repo_dir))
    show_result = await show_tool.execute(path="app.py")
    assert show_result.success
    assert "print('hello')" in show_result.output


@pytest.mark.asyncio
async def test_git_add_and_commit(git_repo_dir):
    (git_repo_dir / "notes.txt").write_text("notes\n")

    add_tool = GitAddTool(str(git_repo_dir))
    add_result = await add_tool.execute(files=["notes.txt"])
    assert add_result.success

    commit_tool = GitCommitTool(str(git_repo_dir))
    commit_result = await commit_tool.execute(message="add notes", files=["notes.txt"])
    assert commit_result.success
    assert "add notes" in commit_result.output

    status_tool = GitStatusTool(str(git_repo_dir))
    status_result = await status_tool.execute()
    assert status_result.success
    assert "Working tree clean" in status_result.output


@pytest.mark.asyncio
async def test_git_checkout_branch(git_repo_dir):
    checkout_tool = GitCheckoutTool(str(git_repo_dir))
    result = await checkout_tool.execute(ref="feature/test", create_branch=True)
    assert result.success

    repo = git.Repo(git_repo_dir)
    assert repo.active_branch.name == "feature/test"
