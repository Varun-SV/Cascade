"""Top header bar: brand name, active model badge, live budget indicator."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, Static


class BudgetIndicator(Static):
    """Live session cost display, updated after each agent turn."""

    cost: reactive[float] = reactive(0.0)

    DEFAULT_CSS = """
    BudgetIndicator {
        color: $text-muted;
        text-style: none;
        padding: 0 1;
    }
    """

    def render(self) -> str:
        if self.cost == 0.0:
            return "  $0.00"
        return f"  ${self.cost:.4f}"

    def update_cost(self, cost: float) -> None:
        self.cost = cost


class CascadeHeader(Widget):
    """Fixed top bar with brand, model badge, and budget."""

    DEFAULT_CSS = """
    CascadeHeader {
        height: 3;
        background: $bg-panel;
        border-bottom: solid $tool-border;
        layout: horizontal;
        align: left middle;
        padding: 0 2;
    }
    CascadeHeader #brand {
        color: $accent-bright;
        text-style: bold;
        width: auto;
        padding: 0 1;
    }
    CascadeHeader #separator {
        color: $text-dim;
        width: auto;
        padding: 0 0;
    }
    CascadeHeader #model-badge {
        color: $text-muted;
        background: $bg-elevated;
        width: auto;
        padding: 0 1;
    }
    CascadeHeader .spacer {
        width: 1fr;
    }
    CascadeHeader BudgetIndicator {
        width: auto;
    }
    CascadeHeader #theme-hint {
        color: $text-dim;
        width: auto;
        padding: 0 1;
    }
    """

    def __init__(self, model_id: str = "planner", **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._model_id = model_id

    def compose(self) -> ComposeResult:
        yield Label(" CASCADE ", id="brand")
        yield Label("│", id="separator")
        yield Label(f" {self._model_id} ", id="model-badge")
        yield Static(classes="spacer")
        yield BudgetIndicator(id="budget")
        yield Label("/theme  /help  ^C quit", id="theme-hint")

    def update_model(self, model_id: str) -> None:
        self.query_one("#model-badge", Label).update(f" {model_id} ")
        self._model_id = model_id

    def update_cost(self, cost: float) -> None:
        self.query_one(BudgetIndicator).update_cost(cost)
