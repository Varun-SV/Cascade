"""Tests for the budget ledger, provider router, and benchmarker."""

from __future__ import annotations

from typing import AsyncIterator

from cascade.budget.ledger import BudgetLedger
from cascade.config import CascadeConfig, ModelConfig
from cascade.providers.base import BaseProvider, Message, Response, Role, StreamChunk, ToolSchema
from cascade.providers.benchmark import ModelBenchmarker
from cascade.providers.router import ProviderRouter


class _FailingProvider(BaseProvider):
    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Response:
        raise RuntimeError("529 overloaded")

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
        return ["failing"]


class _SuccessProvider(BaseProvider):
    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Response:
        return Response(content="use tests to protect behavior and fix the error")

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(content="partial")
        yield StreamChunk(is_final=True)

    async def list_models(self) -> list[str]:
        return ["success"]


def test_budget_ledger_summarizes_and_estimates(tmp_path):
    ledger = BudgetLedger(str(tmp_path / "state.db"))
    ledger.start_task("task-1", "session-1", "fix a bug in auth")
    ledger.record_cost(
        task_id="task-1",
        session_id="session-1",
        tier="planner",
        model_id="planner",
        provider="openai",
        subtask_id="sub-1",
        amount=0.42,
    )

    summary = ledger.summary("session-1")

    assert summary["session_total"] == 0.42
    assert summary["provider_totals"]["openai"] == 0.42
    assert ledger.estimate_cost("fix another bug") > 0


async def test_provider_router_falls_back_to_configured_model():
    config = CascadeConfig(
        models=[
            ModelConfig(id="planner", provider="openai", model="dummy", fallback_models=["backup"]),
            ModelConfig(id="backup", provider="openai", model="dummy"),
        ],
        default_planner="planner",
    )

    def factory(model_id: str) -> BaseProvider:
        if model_id == "planner":
            return _FailingProvider(model="planner")
        return _SuccessProvider(model="backup")

    router = ProviderRouter(model_id="planner", config=config, provider_factory=factory)
    response = await router.generate(messages=[Message(role=Role.USER, content="hello")])

    assert "tests" in response.content


async def test_model_benchmarker_persists_scores(tmp_path):
    benchmarker = ModelBenchmarker(str(tmp_path / "scores.json"))
    provider = _SuccessProvider(model="success")

    result = await benchmarker.benchmark_model(model_id="planner", provider=provider)
    stored = benchmarker.load_scores()

    assert result["score"] > 0
    assert stored["planner"]["score"] == result["score"]
