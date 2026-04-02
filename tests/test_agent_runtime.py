"""Tests for agent/runtime integration."""

from __future__ import annotations

from typing import Any

import pytest

from cascade.api import Cascade, ROOT_DISCOVERY_TOOLS
from cascade.config import CascadeConfig, ModelConfig
from cascade.core.agent import CascadeAgent
from cascade.core.escalation import EscalationPolicy
from cascade.core.task import SubTask
from cascade.providers.base import (
    BaseProvider,
    Message,
    Response,
    ToolCall,
    ToolSchema,
)
from cascade.tools.base import ToolRegistry
from cascade.tools.file_ops import ReadFileTool, WriteFileTool


class RecordingProvider(BaseProvider):
    """A lightweight provider stub for runtime tests."""

    def __init__(self, responses: list[Response] | None = None):
        super().__init__(model="dummy")
        self.responses = responses or []
        self.tool_batches: list[list[ToolSchema]] = []
        self.message_batches: list[list[Message]] = []

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Response:
        self.tool_batches.append(tools or [])
        self.message_batches.append(messages)
        if self.responses:
            return self.responses.pop(0)
        return Response(content="done")

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ):
        if False:
            yield None

    async def list_models(self) -> list[str]:
        return ["dummy"]


@pytest.fixture
def config():
    return CascadeConfig(
        models=[ModelConfig(id="planner", provider="openai", model="dummy")],
        default_planner="planner",
    )


@pytest.mark.asyncio
async def test_root_agent_gets_discovery_tools(tmp_path, config):
    provider = RecordingProvider([Response(content="finished")])
    cascade = Cascade(config=config, project_root=str(tmp_path))
    cascade._providers["planner"] = provider

    result = await cascade.run_async("inspect the repository")

    assert result.success
    tool_names = [tool.name for tool in provider.tool_batches[0]]
    assert "delegate_task" in tool_names
    for tool_name in ROOT_DISCOVERY_TOOLS:
        assert tool_name in tool_names


@pytest.mark.asyncio
async def test_approval_denial_is_returned_to_model(tmp_path, config):
    # Use STRICT mode so write_file requires approval
    from cascade.core.approval import ApprovalMode
    from cascade.config import ApprovalsConfig
    config.approvals = ApprovalsConfig(mode=ApprovalMode.STRICT)

    registry = ToolRegistry()
    registry.register(WriteFileTool(str(tmp_path)))
    provider = RecordingProvider(
        [
            Response(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tool-1",
                        name="write_file",
                        arguments={"path": "blocked.txt", "content": "x"},
                    )
                ],
            ),
            Response(content="saw the denial"),
        ]
    )

    agent = CascadeAgent(
        model_id="planner",
        provider=provider,
        config=config,
        tool_registry=registry,
        escalation_policy=EscalationPolicy(config.escalation),
        allowed_tools=["write_file"],
        provider_factory=lambda _model_id: provider,
    )

    async def deny(_request):
        return False

    success, summary, _confidence = await agent.execute_subtask(
        SubTask(description="Try to write a file"),
        on_approval_request=deny,
    )

    assert success
    assert summary == "saw the denial"
    tool_results = [msg.tool_result for msg in provider.message_batches[1] if msg.tool_result]
    assert tool_results
    assert "Approval denied" in tool_results[-1].content


@pytest.mark.asyncio
async def test_recovered_tool_failure_does_not_force_escalation(tmp_path, config):
    config.escalation.max_retries = 1
    registry = ToolRegistry()
    registry.register(WriteFileTool(str(tmp_path)))
    provider = RecordingProvider(
        [
            Response(
                content="try the write",
                tool_calls=[
                    ToolCall(
                        id="tool-1",
                        name="write_file",
                        arguments={"path": "recovered.txt", "content": "first"},
                    )
                ],
            ),
            Response(
                content="retry the write",
                tool_calls=[
                    ToolCall(
                        id="tool-2",
                        name="write_file",
                        arguments={"path": "recovered.txt", "content": "second"},
                    )
                ],
            ),
            Response(content="Recovered and finished successfully."),
        ]
    )

    agent = CascadeAgent(
        model_id="planner",
        provider=provider,
        config=config,
        tool_registry=registry,
        escalation_policy=EscalationPolicy(config.escalation),
        allowed_tools=["write_file"],
        provider_factory=lambda _model_id: provider,
    )

    calls = 0

    async def flaky_approval(_request):
        nonlocal calls
        calls += 1
        return calls > 1

    success, summary, _confidence = await agent.execute_subtask(
        SubTask(description="Write a file even after one denied attempt"),
        on_approval_request=flaky_approval,
    )

    assert success
    assert summary == "Recovered and finished successfully."
    assert (tmp_path / "recovered.txt").read_text(encoding="utf-8") == "second"
