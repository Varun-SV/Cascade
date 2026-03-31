"""Harness-style end-to-end workflow test against a sandbox repository."""

from __future__ import annotations

from typing import AsyncIterator

from cascade.api import Cascade
from cascade.config import CascadeConfig, ModelConfig
from cascade.core.approval import ApprovalMode
from cascade.providers.base import BaseProvider, Message, Response, StreamChunk, ToolCall, ToolSchema


class ScriptedProvider(BaseProvider):
    """Provider stub that returns a scripted sequence of responses."""

    def __init__(self, responses: list[Response]):
        super().__init__(model="dummy")
        self.responses = responses

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Response:
        if self.responses:
            return self.responses.pop(0)
        return Response(content="done")

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk()

    async def list_models(self) -> list[str]:
        return ["dummy"]


async def test_run_async_can_delegate_and_write_in_sandbox(tmp_path):
    config = CascadeConfig(
        models=[
            ModelConfig(id="planner", provider="openai", model="dummy"),
            ModelConfig(id="worker", provider="openai", model="dummy"),
        ],
        default_planner="planner",
    )
    config.approvals.mode = ApprovalMode.AUTO
    cascade = Cascade(config=config, project_root=str(tmp_path))

    planner = ScriptedProvider(
        [
            Response(
                tool_calls=[
                    ToolCall(
                        id="delegate-1",
                        name="delegate_task",
                        arguments={
                            "title": "Create notes file",
                            "goal": "Write a notes.txt file with project notes.",
                            "model_id": "worker",
                            "tools": ["write_file", "read_file"],
                            "acceptance_criteria": ["notes.txt exists"],
                        },
                    )
                ]
            ),
            Response(content="Created notes.txt through a delegated worker."),
        ]
    )
    worker = ScriptedProvider(
        [
            Response(
                tool_calls=[
                    ToolCall(
                        id="write-1",
                        name="write_file",
                        arguments={"path": "notes.txt", "content": "hello from cascade\n"},
                    )
                ]
            ),
            Response(content="Wrote notes.txt successfully."),
        ]
    )

    cascade._providers["planner"] = planner
    cascade._providers["worker"] = worker

    result = await cascade.run_async("create a notes file")

    assert result.success
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello from cascade\n"
    assert "delegated worker" in result.summary.lower()
