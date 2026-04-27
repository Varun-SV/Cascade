"""Tool call tree-view widget + live terminal output panel."""

from __future__ import annotations

import json
from typing import Any

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, RichLog, Static


class TerminalPanel(Widget):
    """Live scrollable terminal output for run_command tool calls.

    During execution: shows streaming stdout lines in a RichLog.
    On completion: collapses to a single summary line + stores full output.
    """

    is_complete: reactive[bool] = reactive(False)

    DEFAULT_CSS = """
    TerminalPanel {
        margin: 0 0 0 4;
        max-height: 20;
        border: solid $tool-border;
        background: $terminal-bg;
    }
    TerminalPanel RichLog {
        background: $terminal-bg;
        color: $terminal-text;
        height: auto;
        max-height: 18;
        scrollbar-color: $scrollbar;
        scrollbar-color-hover: $scrollbar-hover;
    }
    TerminalPanel #summary {
        color: $terminal-text;
        padding: 0 1;
        display: none;
    }
    TerminalPanel.done {
        max-height: 1;
        border: solid $tool-border;
    }
    TerminalPanel.done RichLog {
        display: none;
    }
    TerminalPanel.done #summary {
        display: block;
    }
    """

    def __init__(self, command: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._command = command
        self._full_output: list[str] = []
        self._exit_code: int | None = None

    def compose(self) -> ComposeResult:
        log = RichLog(highlight=True, markup=False, id="terminal-log")
        log.write(f"$ {self._command}")
        yield log
        yield Static("", id="summary")

    def stream_line(self, line: str) -> None:
        self._full_output.append(line)
        try:
            self.query_one(RichLog).write(line)
        except Exception:
            pass

    def complete(self, exit_code: int, output: str = "") -> None:
        self._exit_code = exit_code
        if output:
            for line in output.splitlines():
                if line not in self._full_output:
                    self._full_output.append(line)
        icon = "✓" if exit_code == 0 else "✗"
        first = self._full_output[0] if self._full_output else ""
        summary = f"{icon} exit {exit_code}  {first[:80]}"
        try:
            self.query_one("#summary", Static).update(summary)
        except Exception:
            pass
        self.add_class("done")
        self.is_complete = True


class ToolCallBlock(Widget):
    """Tree-view display of a single tool call + result."""

    DEFAULT_CSS = """
    ToolCallBlock {
        margin: 1 0 0 2;
        padding: 0 1;
        border-left: solid $tool-border;
        background: $tool-bg;
    }
    ToolCallBlock #tool-header {
        color: $accent;
        text-style: bold;
    }
    ToolCallBlock #tool-input {
        color: $text-muted;
        padding: 0 0 0 2;
    }
    ToolCallBlock #tool-result {
        color: $text-dim;
        padding: 0 0 0 2;
    }
    ToolCallBlock #tool-error {
        color: $error;
        padding: 0 0 0 2;
    }
    """

    def __init__(self, tool_name: str, arguments: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tool_name = tool_name
        self._arguments = arguments
        self._terminal: TerminalPanel | None = None

    def compose(self) -> ComposeResult:
        args_preview = self._format_args(self._arguments)
        yield Label(f"▶ {self._tool_name}", id="tool-header")
        yield Label(f"  └ {args_preview}", id="tool-input")
        if self._tool_name in ("run_command", "start_process"):
            cmd = self._arguments.get("command", "")
            if isinstance(cmd, list):
                cmd = " ".join(cmd)
            self._terminal = TerminalPanel(command=str(cmd))
            yield self._terminal
        yield Label("  └ …", id="tool-result")

    def _format_args(self, args: dict[str, Any]) -> str:
        if not args:
            return "(no args)"
        try:
            s = json.dumps(args, ensure_ascii=False)
            return s[:120] + ("…" if len(s) > 120 else "")
        except Exception:
            return str(args)[:120]

    def set_result(self, content: str, is_error: bool = False) -> None:
        result_id = "#tool-error" if is_error else "#tool-result"
        other_id = "#tool-result" if is_error else "#tool-error"
        preview = content[:200].replace("\n", "  ") + ("…" if len(content) > 200 else "")
        label_text = f"  └ {'✗ ' if is_error else ''}{preview}"
        try:
            self.query_one(result_id, Label).update(label_text)
            # hide the other label if present
            try:
                self.query_one(other_id, Label).display = False
            except Exception:
                pass
        except Exception:
            pass
        if self._terminal and not is_error:
            self._terminal.complete(exit_code=0, output=content)

    def stream_terminal_line(self, line: str) -> None:
        if self._terminal:
            self._terminal.stream_line(line)

    def complete_terminal(self, exit_code: int, output: str) -> None:
        if self._terminal:
            self._terminal.complete(exit_code=exit_code, output=output)
