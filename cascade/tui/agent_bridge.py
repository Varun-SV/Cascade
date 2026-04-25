"""Bridge between Cascade's async run_stream() and Textual's message system."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from textual.message import Message

if TYPE_CHECKING:
    from textual.app import App

    from cascade.api import Cascade
    from cascade.core.approval import ApprovalDecision, ApprovalRequest
    from cascade.core.runtime import ExecutionEvent
    from cascade.core.task import TaskResult


# ── Textual messages posted to the App ──────────────────────────────────────


class AgentStreamEvent(Message):
    """A single ExecutionEvent from run_stream(), forwarded to the TUI."""

    def __init__(self, event: "ExecutionEvent") -> None:
        super().__init__()
        self.event = event


class AgentStreamDone(Message):
    """Signals that the agent has finished (success or failure)."""

    def __init__(self, result: "TaskResult | None", error: str | None) -> None:
        super().__init__()
        self.result = result
        self.error = error


class ApprovalRequested(Message):
    """Posted when the agent needs user approval for a tool call."""

    def __init__(self, request: "ApprovalRequest", pending: "PendingApproval") -> None:
        super().__init__()
        self.request = request
        self.pending = pending


# ── Approval pause/resume ────────────────────────────────────────────────────


@dataclass
class PendingApproval:
    """Pauses the run_stream() worker until the user resolves the prompt."""

    request: "ApprovalRequest"
    _event: asyncio.Event = field(default_factory=asyncio.Event)
    _decision: "ApprovalDecision | None" = field(default=None)

    async def wait(self) -> "ApprovalDecision":
        await self._event.wait()
        assert self._decision is not None
        return self._decision

    def resolve(self, decision: "ApprovalDecision") -> None:
        self._decision = decision
        self._event.set()


# ── Bridge ───────────────────────────────────────────────────────────────────


class AgentBridge:
    """Runs cascade.run_stream() inside a Textual Worker and forwards events."""

    def __init__(self, cascade: "Cascade", app: "App") -> None:
        self._cascade = cascade
        self._app = app
        self._pending_approval: PendingApproval | None = None

        # Replace the cascade approval callback with our TUI-aware version
        self._cascade.on_approval_request = self._tui_approval_handler  # type: ignore[attr-defined]

    async def _tui_approval_handler(
        self, request: "ApprovalRequest"
    ) -> "ApprovalDecision":
        pending = PendingApproval(request=request)
        self._pending_approval = pending
        self._app.post_message(ApprovalRequested(request=request, pending=pending))
        decision = await pending.wait()
        self._pending_approval = None
        return decision

    def resolve_approval(self, decision: "ApprovalDecision") -> None:
        if self._pending_approval is not None:
            self._pending_approval.resolve(decision)

    async def run(self, task: str) -> None:
        """Called inside a Textual Worker (thread=False — shares the asyncio loop)."""
        result = None
        error = None
        try:
            async for event in self._cascade.run_stream(task):
                self._app.post_message(AgentStreamEvent(event=event))
            # run_stream completes — fetch the last task result
            try:
                result = await self._cascade.run_async(task)  # type: ignore[assignment]
            except Exception:
                pass
        except Exception as exc:
            error = str(exc)
        finally:
            self._app.post_message(AgentStreamDone(result=result, error=error))

    async def run_streaming(self, task: str) -> None:
        """Streaming-only run that does not double-execute the task."""
        result = None
        error = None
        try:
            async for event in self._cascade.run_stream(task):
                self._app.post_message(AgentStreamEvent(event=event))
        except Exception as exc:
            error = str(exc)
        finally:
            self._app.post_message(AgentStreamDone(result=result, error=error))


def make_bridge(cascade: "Cascade", app: "App") -> AgentBridge:
    return AgentBridge(cascade=cascade, app=app)
