"""Lightweight model benchmarking and score persistence."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, TypedDict, cast

from cascade.providers.base import BaseProvider, Message, Role


class BenchmarkTask(TypedDict):
    id: str
    prompt: str
    keywords: list[str]


BENCHMARK_TASKS: list[BenchmarkTask] = [
    {
        "id": "reasoning",
        "prompt": "Explain how you would safely refactor a Python function without changing behavior.",
        "keywords": ["test", "behavior", "refactor"],
    },
    {
        "id": "debugging",
        "prompt": "A script crashes with FileNotFoundError. Describe a robust fix.",
        "keywords": ["path", "exists", "error"],
    },
    {
        "id": "planning",
        "prompt": "Outline steps to add unit tests for a module with external dependencies.",
        "keywords": ["mock", "tests", "dependencies"],
    },
]


class ModelBenchmarker:
    """Run a small internal eval set and persist benchmark scores."""

    def __init__(self, score_path: str = "~/.cascade/model_scores.json"):
        self.score_path = Path(score_path).expanduser()
        self.score_path.parent.mkdir(parents=True, exist_ok=True)

    async def benchmark(
        self,
        model_id: str,
        provider_factory: Callable[[str], BaseProvider],
    ) -> dict[str, float]:
        """Benchmark a configured model using a provider factory."""
        provider = provider_factory(model_id)
        result = await self.benchmark_model(model_id=model_id, provider=provider)
        return {key: float(value) for key, value in result.items() if isinstance(value, (int, float))}

    async def benchmark_model(
        self,
        *,
        model_id: str,
        provider: BaseProvider,
    ) -> dict[str, float]:
        """Benchmark a provider instance and persist the result."""
        total_score = 0.0
        total_latency = 0.0
        task_scores: dict[str, float] = {}

        for task in BENCHMARK_TASKS:
            started_at = time.perf_counter()
            response = await provider.generate(
                messages=[Message(role=Role.USER, content=task["prompt"])],
                temperature=0.1,
                max_tokens=512,
            )
            total_latency += time.perf_counter() - started_at
            content = response.content.lower()
            score = sum(1.0 for keyword in task["keywords"] if keyword in content) / len(task["keywords"])
            task_scores[task["id"]] = score
            total_score += score

        result = {
            "score": total_score / len(BENCHMARK_TASKS),
            "average_latency_seconds": total_latency / len(BENCHMARK_TASKS),
            **task_scores,
        }
        self._persist_score(model_id, result)
        return result

    def _persist_score(self, model_id: str, score: dict[str, float]) -> None:
        data = self.load_scores()
        data[model_id] = score
        self.score_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_scores(self) -> dict[str, dict[str, float]]:
        """Load persisted benchmark scores."""
        if not self.score_path.exists():
            return {}
        return cast(dict[str, dict[str, float]], json.loads(self.score_path.read_text(encoding="utf-8")))
