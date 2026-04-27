"""Bottom input bar with slash-command awareness."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Label


class ChatInputBar(Widget):
    """Fixed bottom bar: text input + status label."""

    class Submitted(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    DEFAULT_CSS = """
    ChatInputBar {
        height: 3;
        background: $bg-input;
        border-top: solid $tool-border;
        layout: horizontal;
        align: left middle;
        padding: 0 1;
    }
    ChatInputBar #prompt-symbol {
        color: $accent;
        text-style: bold;
        width: auto;
        padding: 0 1;
    }
    ChatInputBar Input {
        width: 1fr;
        background: $bg-input;
        color: $text-primary;
        border: none;
    }
    ChatInputBar Input:focus {
        border: none;
    }
    ChatInputBar #status-label {
        color: $text-dim;
        width: auto;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Label("›", id="prompt-symbol")
        yield Input(placeholder="Message Cascade… or /help", id="chat-input")
        yield Label("", id="status-label")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value and not self._busy:
            event.input.clear()
            self.post_message(self.Submitted(value=value))

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        inp = self.query_one(Input)
        status = self.query_one("#status-label", Label)
        if busy:
            inp.placeholder = "Working…"
            inp.disabled = True
            status.update("⏳")
        else:
            inp.placeholder = "Message Cascade… or /help"
            inp.disabled = False
            status.update("")
            inp.focus()

    def set_status(self, text: str) -> None:
        self.query_one("#status-label", Label).update(text)
