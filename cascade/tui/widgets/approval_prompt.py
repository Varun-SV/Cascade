"""Inline Y/N approval widget rendered inside the chat stream."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Button, Label, Static

if TYPE_CHECKING:
    from cascade.core.approval import ApprovalDecision, ApprovalRequest
    from cascade.tui.agent_bridge import PendingApproval


class InlineApprovalWidget(Widget):
    """Pauses the agent and asks the user to approve or deny a tool call."""

    DEFAULT_CSS = """
    InlineApprovalWidget {
        margin: 1 2;
        padding: 1 2;
        border: solid $warning;
        background: $bg-elevated;
        height: auto;
    }
    InlineApprovalWidget #approval-title {
        color: $warning;
        text-style: bold;
    }
    InlineApprovalWidget #approval-detail {
        color: $text-muted;
        margin: 0 0 1 0;
    }
    InlineApprovalWidget #approval-buttons {
        layout: horizontal;
        height: auto;
        margin-top: 1;
    }
    InlineApprovalWidget Button {
        margin: 0 1;
        min-width: 10;
    }
    """

    def __init__(
        self,
        request: "ApprovalRequest",
        pending: "PendingApproval",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._request = request
        self._pending = pending

    def compose(self) -> ComposeResult:
        tool = getattr(self._request, "tool_name", str(self._request))
        reason = getattr(self._request, "reason", "")
        yield Label(f"⚠  Approval required: {tool}", id="approval-title")
        if reason:
            yield Static(reason, id="approval-detail")
        with Widget(id="approval-buttons"):
            yield Button("Allow", variant="success", id="btn-allow")
            yield Button("Deny", variant="error", id="btn-deny")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from cascade.core.approval import ApprovalDecision

        approved = event.button.id == "btn-allow"
        decision = ApprovalDecision(approved=bool(approved))
        self._pending.resolve(decision)
        self.remove()
