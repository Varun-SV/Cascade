"""Tests for escalation logic."""

import pytest

from cascade.config import EscalationConfig
from cascade.core.escalation import EscalationPolicy


@pytest.fixture
def policy():
    return EscalationPolicy(EscalationConfig())


class TestT3Escalation:
    def test_low_confidence_escalates(self, policy):
        should, reason = policy.should_t3_escalate(confidence=0.3, retries=0)
        assert should
        assert "confidence" in reason.lower()

    def test_high_confidence_no_escalation(self, policy):
        should, reason = policy.should_t3_escalate(confidence=0.9, retries=0)
        assert not should

    def test_max_retries_escalates(self, policy):
        should, reason = policy.should_t3_escalate(confidence=0.8, retries=3)
        assert should
        assert "retries" in reason.lower()

    def test_parse_error_escalates(self, policy):
        should, reason = policy.should_t3_escalate(
            confidence=0.8, retries=0, error="Could not parse instructions"
        )
        assert should
        assert "parse" in reason.lower()


class TestT2Escalation:
    def test_low_confidence_escalates(self, policy):
        should, reason = policy.should_t2_escalate(confidence=0.2, retries=0)
        assert should

    def test_high_confidence_no_escalation(self, policy):
        should, reason = policy.should_t2_escalate(confidence=0.9, retries=0)
        assert not should

    def test_complex_issue_escalates(self, policy):
        should, reason = policy.should_t2_escalate(
            confidence=0.8, retries=0, error="This requires an architectural decision"
        )
        assert should
        assert "architectural" in reason.lower()


class TestEscalationContext:
    def test_build_context(self, policy):
        ctx = policy.build_context(
            from_tier="t2",
            reason="Too complex",
            task_description="Refactor auth module",
            attempts=2,
            errors=["Error 1", "Error 2"],
        )
        assert ctx.from_tier == "t2"
        assert ctx.reason == "Too complex"
        assert ctx.attempts_made == 2
        assert len(ctx.errors) == 2
