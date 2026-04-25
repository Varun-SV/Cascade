"""Root Textual application for Cascade TUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from textual.app import App, ComposeResult

from cascade.tui.themes import THEMES, apply_theme, load_saved_theme


class CascadeTUIApp(App):
    """Full-screen Cascade TUI: chat, tools, themes."""

    # Load the default (cascade) theme CSS at startup
    CSS_PATH = str(Path(__file__).parent / "themes" / "cascade.tcss")

    TITLE = "Cascade"
    SUB_TITLE = "AI Agent"

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_chat", "Clear chat"),
        ("f1", "show_help", "Help"),
    ]

    def __init__(
        self,
        config_path: Optional[str] = None,
        project_root: Optional[str] = None,
        budget: Optional[float] = None,
        approval_mode: Optional[str] = None,
        verbose: bool = False,
        no_auditor: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._config_path = config_path
        self._project_root = project_root
        self._budget = budget
        self._approval_mode = approval_mode
        self._verbose = verbose
        self._no_auditor = no_auditor
        self._cascade: Any = None

    def _build_cascade(self) -> Any:
        """Build the Cascade instance using the same factory as the CLI."""
        from cascade.api import Cascade
        from cascade.config import load_config

        config = load_config(self._config_path)
        if self._project_root:
            config.project_root = self._project_root
        if self._budget is not None:
            config.budget.enabled = True
            config.budget.session_max_cost = self._budget
        if self._approval_mode:
            from cascade.core.approval import ApprovalMode
            config.approvals.mode = ApprovalMode(self._approval_mode)
        if self._verbose:
            config.verbose = True
        if self._no_auditor:
            config.auditor_enabled = False

        return Cascade(config=config)

    def on_mount(self) -> None:
        # Apply saved theme
        saved = load_saved_theme()
        if saved != "cascade":
            apply_theme(self, saved)

        # Build cascade instance and push chat screen
        self._cascade = self._build_cascade()
        from cascade.tui.screens.chat import ChatScreen
        self.push_screen(ChatScreen(cascade=self._cascade))

    def compose(self) -> ComposeResult:
        return iter([])

    def action_change_theme(self, theme_name: str) -> None:
        apply_theme(self, theme_name)

    def action_clear_chat(self) -> None:
        from cascade.tui.screens.chat import ChatScreen
        screen = self.query_one(ChatScreen)
        if screen:
            screen.action_clear_chat()

    def action_show_help(self) -> None:
        from cascade.tui.screens.chat import ChatScreen
        screen = self.query_one(ChatScreen)
        if screen:
            screen.message_list.add_system_bubble(
                "**Keyboard shortcuts**\n"
                "  Ctrl+C   — Quit\n"
                "  Ctrl+L   — Clear chat\n"
                "  F1       — This help\n\n"
                "**Slash commands**\n"
                "  /help    — List all commands\n"
                "  /theme   — Change theme\n"
                "  /clear   — Clear chat\n"
                "  /search  — Web search\n"
                "  /run     — Run a command\n"
                "  /read    — Read a file\n"
                "  /budget  — Show session cost\n"
                "  /exit    — Quit"
            )
