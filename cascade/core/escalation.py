"""Confidence-based escalation engine."""

from __future__ import annotations

from pydantic import BaseModel

from cascade.config import EscalationConfig


class EscalationContext(BaseModel):
    """Context passed to a higher tier when escalating."""

    from_tier: str
    reason: str
    task_description: str
    attempts_made: int = 0
    errors: list[str] = []
    partial_result: str = ""


class EscalationPolicy:
    """Evaluates whether a task should be escalated to a higher tier."""

    def __init__(self, config: EscalationConfig):
        self.config = config

    def should_t3_escalate(
        self, confidence: float, retries: int, error: str = ""
    ) -> tuple[bool, str]:
        """
        Determine if T3 should escalate to T2.

        Returns (should_escalate, reason).
        """
        if confidence < self.config.t3_confidence_threshold:
            return True, f"Confidence {confidence:.2f} below threshold {self.config.t3_confidence_threshold}"

        if retries >= self.config.max_retries_before_escalation:
            return True, f"Max retries ({retries}) reached"

        if error and "parse" in error.lower():
            return True, f"Parse error: {error}"

        if error and "not found" in error.lower():
            return True, f"Resource error: {error}"

        return False, ""

    def should_t2_escalate(
        self, confidence: float, retries: int, error: str = ""
    ) -> tuple[bool, str]:
        """
        Determine if T2 should escalate to T1.

        Returns (should_escalate, reason).
        """
        if confidence < self.config.t2_confidence_threshold:
            return True, f"Confidence {confidence:.2f} below threshold {self.config.t2_confidence_threshold}"

        if retries >= self.config.max_retries_before_escalation:
            return True, f"Max retries ({retries}) reached"

        # Complex reasoning indicators
        complex_keywords = [
            "architectural", "design decision", "refactor", "security",
            "breaking change", "migration", "unclear requirements",
        ]
        if error:
            for keyword in complex_keywords:
                if keyword in error.lower():
                    return True, f"Complex issue detected: {keyword}"

        return False, ""

    def build_context(
        self,
        from_tier: str,
        reason: str,
        task_description: str,
        attempts: int = 0,
        errors: list[str] | None = None,
        partial_result: str = "",
    ) -> EscalationContext:
        """Build an escalation context to pass to the higher tier."""
        return EscalationContext(
            from_tier=from_tier,
            reason=reason,
            task_description=task_description,
            attempts_made=attempts,
            errors=errors or [],
            partial_result=partial_result,
        )
