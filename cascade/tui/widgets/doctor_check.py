"""Doctor check row widget: spinner → pass/fail + optional Fix button."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, LoadingIndicator, Static


@dataclass
class CheckResult:
    passed: bool
    detail: str
    fix_hint: str = ""
    fix_key: str = ""


class FixFormModal(ModalScreen[str | None]):
    """Modal screen that prompts the user to supply a fix value (e.g. an API key)."""

    DEFAULT_CSS = """
    FixFormModal {
        align: center middle;
    }
    FixFormModal #modal-box {
        background: $bg-elevated;
        border: solid $warning;
        padding: 2 4;
        width: 60;
        height: auto;
    }
    FixFormModal #modal-title {
        color: $warning;
        text-style: bold;
        margin-bottom: 1;
    }
    FixFormModal #modal-hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    FixFormModal Input {
        margin-bottom: 1;
    }
    FixFormModal #btn-row {
        layout: horizontal;
        height: auto;
    }
    FixFormModal Button {
        margin-right: 1;
    }
    """

    def __init__(self, title: str, hint: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._hint = hint

    def compose(self) -> ComposeResult:
        with Widget(id="modal-box"):
            yield Label(self._title, id="modal-title")
            yield Static(self._hint, id="modal-hint")
            yield Input(password=True, placeholder="Enter value…", id="fix-input")
            with Widget(id="btn-row"):
                yield Button("Apply", variant="success", id="btn-apply")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-apply":
            value = self.query_one("#fix-input", Input).value.strip()
            self.dismiss(value if value else None)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        self.dismiss(value if value else None)


class DoctorCheckRow(Widget):
    """A single check row in the doctor screen."""

    DEFAULT_CSS = """
    DoctorCheckRow {
        height: auto;
        layout: horizontal;
        align: left middle;
        padding: 0 2;
        margin: 0 0 1 0;
    }
    DoctorCheckRow #spinner {
        width: 3;
    }
    DoctorCheckRow #status-icon {
        width: 3;
        display: none;
    }
    DoctorCheckRow #check-name {
        width: 30;
        color: $text-primary;
    }
    DoctorCheckRow #check-detail {
        width: 1fr;
        color: $text-muted;
    }
    DoctorCheckRow #fix-btn {
        width: auto;
        display: none;
    }
    DoctorCheckRow.passed #status-icon {
        display: block;
        color: $success;
    }
    DoctorCheckRow.failed #status-icon {
        display: block;
        color: $error;
    }
    DoctorCheckRow.passed #spinner {
        display: none;
    }
    DoctorCheckRow.failed #spinner {
        display: none;
    }
    DoctorCheckRow.failed #fix-btn {
        display: block;
    }
    """

    def __init__(
        self,
        check_id: str,
        name: str,
        on_fix: Callable[[str, str], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(id=f"check-{check_id}", **kwargs)
        self._check_id = check_id
        self._name: str = name
        self._on_fix = on_fix
        self._result: CheckResult | None = None

    def compose(self) -> ComposeResult:
        yield LoadingIndicator(id="spinner")
        yield Label("", id="status-icon")
        yield Label(self._name, id="check-name")
        yield Label("checking…", id="check-detail")
        yield Button("Fix", variant="warning", id="fix-btn")

    def complete(self, result: CheckResult) -> None:
        self._result = result
        icon = self.query_one("#status-icon", Label)
        detail = self.query_one("#check-detail", Label)
        icon.update("✓" if result.passed else "✗")
        detail.update(result.detail)
        if result.passed:
            self.add_class("passed")
        else:
            self.add_class("failed")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "fix-btn" and self._result and self._on_fix:
            self._on_fix(self._check_id, self._result.fix_key)
