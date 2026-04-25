"""Main interactive chat screen."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.screen import Screen
from textual.worker import Worker, WorkerState

from cascade.tui.agent_bridge import (
    AgentBridge,
    AgentStreamDone,
    AgentStreamEvent,
    ApprovalRequested,
)
from cascade.tui.slash_commands import SlashCommandHandler
from cascade.tui.widgets.approval_prompt import InlineApprovalWidget
from cascade.tui.widgets.header import CascadeHeader
from cascade.tui.widgets.input_bar import ChatInputBar
from cascade.tui.widgets.message_list import MessageBubble, MessageList
from cascade.tui.widgets.tool_block import ToolCallBlock

if TYPE_CHECKING:
    from cascade.api import Cascade


class ChatScreen(Screen):
    """Full-screen interactive chat with Cascade."""

    DEFAULT_CSS = """
    ChatScreen {
        layout: vertical;
        background: $bg-base;
    }
    """

    BINDINGS = [
        ("ctrl+l", "clear_chat", "Clear"),
        ("escape", "blur_input", "Blur"),
    ]

    def __init__(self, cascade: "Cascade", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.cascade = cascade
        self._bridge: AgentBridge | None = None
        self._current_bubble: MessageBubble | None = None
        self._current_tool_block: ToolCallBlock | None = None
        self._session_cost: float = 0.0

    def compose(self) -> ComposeResult:
        model_id = getattr(self.cascade, "_config", None)
        if model_id:
            model_id = getattr(model_id, "default_planner", "planner")
        else:
            model_id = "planner"
        yield CascadeHeader(model_id=str(model_id), id="header")
        yield MessageList(id="message-list")
        yield ChatInputBar(id="input-bar")

    def on_mount(self) -> None:
        self.message_list.add_system_bubble(
            "Welcome to Cascade. Type a message to start, or /help for commands."
        )

    @property
    def message_list(self) -> MessageList:
        return self.query_one(MessageList)

    @property
    def input_bar(self) -> ChatInputBar:
        return self.query_one(ChatInputBar)

    @property
    def header(self) -> CascadeHeader:
        return self.query_one(CascadeHeader)

    # ── Input handling ──────────────────────────────────────────────────────

    async def on_chat_input_bar_submitted(self, event: ChatInputBar.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        if text.startswith("/"):
            handler = SlashCommandHandler(self)
            await handler.dispatch(text)
        else:
            self.message_list.add_user_bubble(text)
            await self.start_agent(text)

    async def start_agent(self, task: str) -> None:
        if self._bridge is not None:
            self.message_list.add_system_bubble("Agent is already running. Please wait.")
            return
        self._current_bubble = self.message_list.add_ai_bubble()
        self._current_tool_block = None
        self.input_bar.set_busy(True)
        self._bridge = AgentBridge(cascade=self.cascade, app=self.app)
        self.run_worker(
            self._bridge.run_streaming(task),
            exclusive=False,
            thread=False,
            name="agent-worker",
        )

    # ── Stream event routing ────────────────────────────────────────────────

    def on_agent_stream_event(self, message: AgentStreamEvent) -> None:
        event = message.event
        et = event.event_type
        payload: dict[str, Any] = event.payload if isinstance(event.payload, dict) else {}

        if et == "agent.started":
            self.input_bar.set_status("⏳ Working…")

        elif et in ("agent.response", "agent.completed"):
            if event.message and self._current_bubble:
                self._current_bubble.append_text(event.message)
            self.message_list.scroll_end(animate=False)

        elif et == "agent.thinking":
            if self._current_bubble:
                self._current_bubble.show_thinking(event.message or payload.get("content", ""))

        elif et == "tool.call":
            tool_name = payload.get("tool_name", payload.get("name", "unknown"))
            args = payload.get("arguments", payload.get("input", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {"raw": args}
            if self._current_bubble:
                self._current_tool_block = self._current_bubble.add_tool_block(
                    tool_name=tool_name, arguments=args
                )
            self.message_list.scroll_end(animate=False)

        elif et == "tool.result":
            content = payload.get("content", event.message or "")
            is_error = payload.get("is_error", False)
            exit_code = payload.get("exit_code", 0 if not is_error else 1)
            if self._current_tool_block:
                self._current_tool_block.set_result(str(content), is_error=bool(is_error))
                if not is_error:
                    self._current_tool_block.complete_terminal(
                        exit_code=int(exit_code), output=str(content)
                    )
            self.message_list.scroll_end(animate=False)

        elif et == "auditor.blocked":
            reason = payload.get("reason", event.message or "Blocked by safety auditor")
            if self._current_bubble:
                self._current_bubble.append_text(f"\n\n[bold red]🛡 Auditor blocked:[/bold red] {reason}")

        elif et in ("provider.context.summarized", "provider.context.truncated"):
            self.input_bar.set_status("📝 Summarising context…")

        elif et == "agent.reflection":
            self.input_bar.set_status("🔄 Reflecting…")

        elif et == "agent.escalated":
            if self._current_bubble:
                self._current_bubble.append_text(
                    "\n\n[yellow]⚠ Escalated to parent agent.[/yellow]"
                )

        elif et == "agent.delegated":
            delegate_to = payload.get("model_id", "sub-agent")
            self.input_bar.set_status(f"🔀 Delegating to {delegate_to}…")

        # Update cost from payload if present
        cost = payload.get("cost") or event.cost
        if cost:
            self._session_cost += float(cost)
            self.header.update_cost(self._session_cost)

    def on_agent_stream_done(self, message: AgentStreamDone) -> None:
        self._bridge = None
        self._current_tool_block = None
        self.input_bar.set_busy(False)
        self.input_bar.set_status("")
        if message.error:
            if self._current_bubble:
                self._current_bubble.append_text(
                    f"\n\n[bold red]Error:[/bold red] {message.error}"
                )
            else:
                self.message_list.add_error_bubble(message.error)
        self._current_bubble = None
        self.message_list.scroll_end(animate=False)

    def on_approval_requested(self, message: ApprovalRequested) -> None:
        widget = InlineApprovalWidget(
            request=message.request,
            pending=message.pending,
        )
        if self._current_bubble:
            self._current_bubble.mount_widget(widget)
        else:
            self.message_list.mount(widget)
        self.message_list.scroll_end(animate=False)

    # ── Actions ─────────────────────────────────────────────────────────────

    def action_clear_chat(self) -> None:
        self.message_list.clear_messages()
        self.message_list.add_system_bubble("Chat cleared.")

    def action_blur_input(self) -> None:
        self.input_bar.set_status("")
