"""Ledger-backed cost tracking and budget enforcement."""

from __future__ import annotations

import uuid
from typing import Optional

from cascade.budget.ledger import BudgetLedger
from cascade.config import BudgetConfig, CascadeConfig


class BudgetExceededError(Exception):
    """Raised when a configured budget ceiling is exceeded."""


class CostTracker:
    """Track session and task costs while persisting ledger entries."""

    def __init__(self, config: BudgetConfig, cascade_config: Optional[CascadeConfig] = None):
        self.config = config
        self.cascade_config = cascade_config
        self.ledger = BudgetLedger(config.ledger_path)
        self.session_id = str(uuid.uuid4())
        self.current_task_id = ""
        self.current_task_description = ""
        self.costs: dict[str, float] = {}
        self._tier_costs: dict[str, float] = {}

    @property
    def total_cost(self) -> float:
        """Return current session spend."""
        return self.ledger.session_total(self.session_id)

    def start_task(self, task_id: str, description: str) -> None:
        """Begin ledger tracking for a task."""
        self.current_task_id = task_id
        self.current_task_description = description
        self.ledger.start_task(task_id, self.session_id, description)

    def add_cost(
        self,
        model_id: str,
        amount: float,
        *,
        subtask_id: str = "",
        tier: str = "",
        provider: str = "",
        task_id: str = "",
    ) -> None:
        """Record cost for a model and enforce configured limits."""
        resolved_task_id = task_id or self.current_task_id
        if not resolved_task_id:
            return

        resolved_provider = provider
        if not resolved_provider and self.cascade_config is not None:
            try:
                resolved_provider = self.cascade_config.get_model(model_id).provider
            except Exception:
                resolved_provider = "unknown"

        resolved_tier = tier or model_id
        self.costs[model_id] = self.costs.get(model_id, 0.0) + amount
        self._tier_costs[resolved_tier] = self._tier_costs.get(resolved_tier, 0.0) + amount
        self.ledger.record_cost(
            task_id=resolved_task_id,
            session_id=self.session_id,
            tier=resolved_tier,
            model_id=model_id,
            provider=resolved_provider or "unknown",
            subtask_id=subtask_id,
            amount=amount,
        )
        if self.config.enabled:
            self._check_limits(model_id=model_id, tier=resolved_tier, task_id=resolved_task_id)

    def _check_limits(self, *, model_id: str, tier: str, task_id: str) -> None:
        if self.config.session_max_cost is not None and self.total_cost > self.config.session_max_cost:
            raise BudgetExceededError(
                f"Session budget exceeded: ${self.total_cost:.4f} > ${self.config.session_max_cost:.4f}"
            )

        if self.config.task_max_cost is not None:
            task_total = self.ledger.task_total(task_id)
            if task_total > self.config.task_max_cost:
                raise BudgetExceededError(
                    f"Task budget exceeded: ${task_total:.4f} > ${self.config.task_max_cost:.4f}"
                )

        model_limit = self.config.model_max_cost.get(model_id)
        if model_limit is not None and self.costs.get(model_id, 0.0) > model_limit:
            raise BudgetExceededError(
                f"Model budget exceeded for {model_id}: ${self.costs[model_id]:.4f} > ${model_limit:.4f}"
            )

        tier_limit = self.config.tier_max_costs.get(tier)
        if tier_limit is not None and self._tier_costs.get(tier, 0.0) > tier_limit:
            raise BudgetExceededError(
                f"Tier budget exceeded for {tier}: ${self._tier_costs[tier]:.4f} > ${tier_limit:.4f}"
            )

    def estimate_cost(self, task_description: str) -> float:
        """Estimate task cost from history and fallback priors."""
        return self.ledger.estimate_cost(task_description)

    def get_summary(self) -> dict[str, str]:
        """Return per-model and session cost summaries."""
        summary = {model_id: f"${cost:.4f}" for model_id, cost in sorted(self.costs.items())}
        summary["total"] = f"${self.total_cost:.4f}"
        return summary

    def budget_summary(self) -> dict[str, object]:
        """Return a structured summary suitable for CLI and JSON output."""
        return self.ledger.summary(self.session_id)
