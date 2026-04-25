"""Scrollable message history: user and AI bubbles."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.scroll_view import ScrollView
from textual.widget import Widget
from textual.widgets import Label, Static

from cascade.tui.widgets.thinking_block import ThinkingBlock
from cascade.tui.widgets.tool_block import ToolCallBlock


class MessageBubble(Widget):
    """A single message — either from the user or the AI."""

    DEFAULT_CSS = """
    MessageBubble {
        height: auto;
        margin: 1 2;
        padding: 1 2;
        border-radius: 1;
    }
    MessageBubble.user-bubble {
        background: $accent-dim;
        color: $text-user;
        margin-left: 20;
        border-left: solid $accent;
        text-align: right;
    }
    MessageBubble.ai-bubble {
        background: $bg-panel;
        color: $text-ai;
        margin-right: 20;
        border-left: solid $tool-border;
    }
    MessageBubble.error-bubble {
        background: $auditor-bg;
        border-left: solid $error;
        color: $error;
        margin-right: 20;
    }
    MessageBubble.system-bubble {
        background: $bg-elevated;
        color: $text-dim;
        text-style: italic;
        margin-right: 30;
        margin-left: 30;
        text-align: center;
    }
    MessageBubble #bubble-role {
        text-style: bold;
        margin-bottom: 1;
        color: $text-dim;
    }
    MessageBubble #bubble-text {
        height: auto;
    }
    """

    def __init__(self, role: str, text: str = "", **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._role = role
        self._text = text
        self._text_widget: Static | None = None
        self._thinking: ThinkingBlock | None = None
        self._tool_blocks: list[ToolCallBlock] = []
        self.add_class(f"{role}-bubble")

    def compose(self) -> ComposeResult:
        if self._role not in ("system", "error"):
            role_label = "You" if self._role == "user" else "Cascade"
            yield Label(role_label, id="bubble-role")
        self._text_widget = Static(self._text, id="bubble-text", markup=True)
        yield self._text_widget

    def append_text(self, chunk: str) -> None:
        self._text += chunk
        if self._text_widget:
            self._text_widget.update(self._text)

    def set_text(self, text: str) -> None:
        self._text = text
        if self._text_widget:
            self._text_widget.update(text)

    def show_thinking(self, text: str) -> None:
        if self._thinking is None:
            self._thinking = ThinkingBlock()
            self.mount(self._thinking)
        self._thinking.update_text(text)

    def add_tool_block(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallBlock:
        block = ToolCallBlock(tool_name=tool_name, arguments=arguments)
        self._tool_blocks.append(block)
        self.mount(block)
        return block

    def get_last_tool_block(self) -> ToolCallBlock | None:
        return self._tool_blocks[-1] if self._tool_blocks else None

    def mount_widget(self, widget: Widget) -> None:
        self.mount(widget)


class MessageList(Widget):
    """Scrollable container for all message bubbles."""

    DEFAULT_CSS = """
    MessageList {
        height: 1fr;
        overflow-y: auto;
        background: $bg-base;
        scrollbar-color: $scrollbar;
        scrollbar-color-hover: $scrollbar-hover;
        padding: 0 0 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        return iter([])

    def add_user_bubble(self, text: str) -> MessageBubble:
        bubble = MessageBubble(role="user", text=text)
        self.mount(bubble)
        self.scroll_end(animate=False)
        return bubble

    def add_ai_bubble(self) -> MessageBubble:
        bubble = MessageBubble(role="ai")
        self.mount(bubble)
        self.scroll_end(animate=False)
        return bubble

    def add_system_bubble(self, text: str) -> MessageBubble:
        bubble = MessageBubble(role="system", text=text)
        self.mount(bubble)
        self.scroll_end(animate=False)
        return bubble

    def add_error_bubble(self, text: str) -> MessageBubble:
        bubble = MessageBubble(role="error", text=f"✗ {text}")
        self.mount(bubble)
        self.scroll_end(animate=False)
        return bubble

    def clear_messages(self) -> None:
        for child in list(self.children):
            child.remove()
