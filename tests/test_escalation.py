"""Tests for escalation logic."""

import pytest

from cascade.config import EscalationConfig
from cascade.core.escalation import EscalationPolicy


@pytest.fixture
def policy():
    return EscalationPolicy(EscalationConfig(confidence_threshold=0.5, max_retries=2))


class TestEscalation:
    def test_low_confidence_escalates(self, policy):
        should = policy.should_escalate(confidence=0.3, attempts=0)
        assert should

    def test_high_confidence_no_escalation(self, policy):
        should = policy.should_escalate(confidence=0.9, attempts=0)
        assert not should

    def test_max_retries_escalates(self, policy):
        should = policy.should_escalate(confidence=0.8, attempts=3)
        assert should

    def test_consecutive_tool_failures_escalates(self, policy):
        should = policy.should_escalate(confidence=0.8, attempts=0, tools_failed=3)
        assert should


class TestEscalationContext:
    def test_build_context(self, policy):
        ctx = policy.build_context(
            failed_model="local-worker",
            reason="Too complex",
            task_description="Refactor auth module",
            attempts=2,
            errors=["Error 1", "Error 2"],
        )
        assert ctx.failed_model == "local-worker"
        assert ctx.reason == "Too complex"
        assert ctx.attempts == 2
        assert len(ctx.errors) == 2
