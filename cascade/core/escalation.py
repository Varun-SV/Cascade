"""Escalation logic for the N-Tier Fractal architecture."""

from __future__ import annotations

from pydantic import BaseModel, Field

from cascade.config import EscalationConfig


class EscalationContext(BaseModel):
    """Context passed back to a parent agent when a child escalates."""

    failed_model: str
    reason: str
    task_description: str
    attempts: int
    errors: list[str] = Field(default_factory=list)


class EscalationPolicy:
    """Evaluates whether an agent should escalate to its parent."""

    def __init__(self, config: EscalationConfig):
        self.config = config

    def should_escalate(self, confidence: float, attempts: int, tools_failed: int = 0) -> bool:
        """
        Determine if the current agent should give up and escalate.
        
        Args:
            confidence: Current confidence score (0.0 to 1.0)
            attempts: Number of consecutive failed attempts or retries
            tools_failed: Number of consecutive tool failures
            
        Returns:
            True if it's time to escalate to the parent.
        """
        if confidence < self.config.confidence_threshold:
            return True
            
        if attempts > self.config.max_retries:
            return True
            
        if tools_failed >= 3:
            return True
            
        return False

    def build_context(
        self,
        failed_model: str,
        reason: str,
        task_description: str,
        attempts: int,
        errors: list[str],
    ) -> EscalationContext:
        """Create an escalation payload to send up the tree."""
        return EscalationContext(
            failed_model=failed_model,
            reason=reason,
            task_description=task_description,
            attempts=attempts,
            errors=errors,
        )
