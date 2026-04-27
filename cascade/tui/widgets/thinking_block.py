"""Collapsible thinking/reasoning block rendered inside an AI bubble."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, Static


class ThinkingBlock(Widget):
    """Shows agent reasoning — collapsed by default, expandable on click."""

    collapsed: reactive[bool] = reactive(True)

    DEFAULT_CSS = """
    ThinkingBlock {
        margin: 0 0 1 2;
        padding: 0;
    }
    ThinkingBlock #think-header {
        color: $thinking-text;
        text-style: italic;
        cursor: pointer;
    }
    ThinkingBlock #think-content {
        color: $thinking-text;
        padding: 0 0 0 3;
        display: none;
    }
    ThinkingBlock.expanded #think-content {
        display: block;
    }
    """

    def __init__(self, text: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._text = text

    def compose(self) -> ComposeResult:
        yield Label("💭 Thinking… [dim](click to expand)[/dim]", id="think-header")
        yield Static(self._text, id="think-content", markup=False)

    def on_click(self) -> None:
        self.collapsed = not self.collapsed
        self.toggle_class("expanded")

    def update_text(self, text: str) -> None:
        self._text = text
        try:
            self.query_one("#think-content", Static).update(text)
        except Exception:
            pass
