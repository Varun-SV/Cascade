"""Cost tracking and budget management."""

from __future__ import annotations

from cascade.config import BudgetConfig


class BudgetExceededError(Exception):
    """Raised when a cost budget is exceeded."""

    pass


class CostTracker:
    """Tracks costs per tier and enforces optional budget limits."""

    def __init__(self, config: BudgetConfig):
        self.config = config
        self.costs: dict[str, float] = {
            "t1": 0.0,
            "t2": 0.0,
            "t3": 0.0,
        }

    @property
    def total_cost(self) -> float:
        """Total cost across all tiers."""
        return sum(self.costs.values())

    def add_cost(self, tier: str, amount: float) -> None:
        """Record a cost and check budget limits."""
        tier = tier.lower()
        if tier not in self.costs:
            self.costs[tier] = 0.0

        self.costs[tier] += amount

        if self.config.enabled:
            self._check_limits(tier)

    def _check_limits(self, tier: str) -> None:
        """Check if any budget limit has been exceeded."""
        # Per-tier limits
        tier_limits = {
            "t1": self.config.t1_max_cost,
            "t2": self.config.t2_max_cost,
            "t3": self.config.t3_max_cost,
        }

        limit = tier_limits.get(tier)
        if limit is not None and self.costs[tier] > limit:
            raise BudgetExceededError(
                f"Budget exceeded for {tier}: ${self.costs[tier]:.4f} > ${limit:.4f}"
            )

        # Session limit
        if self.config.session_max_cost is not None:
            if self.total_cost > self.config.session_max_cost:
                raise BudgetExceededError(
                    f"Session budget exceeded: ${self.total_cost:.4f} > "
                    f"${self.config.session_max_cost:.4f}"
                )

    def get_remaining(self, tier: str) -> float | None:
        """Get remaining budget for a tier. Returns None if no limit set."""
        if not self.config.enabled:
            return None

        tier_limits = {
            "t1": self.config.t1_max_cost,
            "t2": self.config.t2_max_cost,
            "t3": self.config.t3_max_cost,
        }

        limit = tier_limits.get(tier.lower())
        if limit is None:
            return None
        return max(0, limit - self.costs.get(tier.lower(), 0))

    def get_summary(self) -> dict[str, str]:
        """Get a human-readable cost summary."""
        summary = {}
        for tier, cost in self.costs.items():
            remaining = self.get_remaining(tier)
            if remaining is not None:
                summary[tier] = f"${cost:.4f} (${remaining:.4f} remaining)"
            else:
                summary[tier] = f"${cost:.4f}"

        remaining_total = None
        if self.config.enabled and self.config.session_max_cost is not None:
            remaining_total = max(0, self.config.session_max_cost - self.total_cost)

        if remaining_total is not None:
            summary["total"] = f"${self.total_cost:.4f} (${remaining_total:.4f} remaining)"
        else:
            summary["total"] = f"${self.total_cost:.4f}"

        return summary
