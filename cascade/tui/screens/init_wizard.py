"""cascade init — interactive multi-step provider setup wizard."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Static,
    TextArea,
)


# ── Wizard state ─────────────────────────────────────────────────────────────


@dataclass
class AzureEndpoint:
    name: str = ""
    base_url: str = ""
    api_key: str = ""
    api_version: str = "2024-02-01"
    deployment_name: str = ""


@dataclass
class WizardState:
    providers: list[str] = field(default_factory=list)

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # OpenAI
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "gpt-4o"

    # OpenAI-compatible
    compat_name: str = "custom"
    compat_base_url: str = ""
    compat_api_key: str = ""
    compat_model: str = "gpt-4o"

    # Azure
    azure_endpoints: list[AzureEndpoint] = field(default_factory=list)
    azure_model: str = "gpt-4o"

    # Google
    google_api_key: str = ""
    google_model: str = "gemini-2.0-flash"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"

    # Global settings
    default_planner: str = "planner"
    budget_enabled: bool = False
    budget_max_cost: float = 5.0
    approval_mode: str = "guarded"

    target_path: str = "."
    global_config: bool = False


# ── YAML generation ───────────────────────────────────────────────────────────


def generate_yaml(state: WizardState) -> str:
    models: list[dict[str, Any]] = []
    api_keys: dict[str, str] = {}
    azure_endpoints_cfg: list[dict[str, Any]] = []

    if "anthropic" in state.providers:
        models.append({
            "id": "planner",
            "provider": "anthropic",
            "model": state.anthropic_model,
            "temperature": 0.3,
            "max_tokens": 8192,
        })
        if state.anthropic_api_key:
            api_keys["anthropic"] = state.anthropic_api_key

    if "openai" in state.providers:
        entry: dict[str, Any] = {
            "id": "worker",
            "provider": "openai",
            "model": state.openai_model,
            "temperature": 0.2,
            "max_tokens": 4096,
        }
        models.append(entry)
        if state.openai_api_key:
            api_keys["openai"] = state.openai_api_key

    if "openai-compatible" in state.providers:
        models.append({
            "id": state.compat_name,
            "provider": "openai",
            "model": state.compat_model,
            "temperature": 0.2,
            "max_tokens": 4096,
        })
        if state.compat_api_key:
            api_keys["openai"] = api_keys.get("openai", state.compat_api_key)

    if "azure" in state.providers:
        for ep in state.azure_endpoints:
            if ep.name:
                azure_endpoints_cfg.append({
                    "name": ep.name,
                    "base_url": ep.base_url,
                    "api_key": ep.api_key,
                    "api_version": ep.api_version,
                    "deployment_name": ep.deployment_name,
                })
                models.append({
                    "id": f"azure-{ep.name}",
                    "provider": "azure",
                    "azure_endpoint": ep.name,
                    "model": state.azure_model,
                    "temperature": 0.2,
                    "max_tokens": 4096,
                })

    if "google" in state.providers:
        models.append({
            "id": "gemini",
            "provider": "google",
            "model": state.google_model,
            "temperature": 0.2,
            "max_tokens": 4096,
        })
        if state.google_api_key:
            api_keys["google"] = state.google_api_key

    if "ollama" in state.providers:
        models.append({
            "id": "local",
            "provider": "ollama",
            "model": state.ollama_model,
            "temperature": 0.1,
            "max_tokens": 2048,
        })

    if not models:
        models.append({
            "id": "planner",
            "provider": "anthropic",
            "model": "claude-sonnet-4-20250514",
            "temperature": 0.3,
            "max_tokens": 8192,
        })

    planner_id = state.default_planner
    if planner_id not in [m["id"] for m in models]:
        planner_id = models[0]["id"]

    cfg: dict[str, Any] = {
        "default_planner": planner_id,
        "models": models,
    }
    if api_keys:
        cfg["api_keys"] = api_keys
    if azure_endpoints_cfg:
        cfg["azure_endpoints"] = azure_endpoints_cfg
    if "ollama" in state.providers and state.ollama_base_url:
        cfg["ollama"] = {"base_url": state.ollama_base_url}
    cfg["budget"] = {
        "enabled": state.budget_enabled,
        "session_max_cost": state.budget_max_cost if state.budget_enabled else None,
    }
    cfg["approvals"] = {"mode": state.approval_mode}

    return yaml.dump(cfg, default_flow_style=False, sort_keys=False, allow_unicode=True)  # type: ignore[no-any-return]


# ── Shared wizard navigation ──────────────────────────────────────────────────


WIZARD_STEPS = [
    "welcome",
    "providers",
    "provider-config",
    "planner",
    "budget",
    "approval",
    "confirm",
]


class WizardNav(Widget):
    """Bottom navigation bar with Back / Next buttons."""

    DEFAULT_CSS = """
    WizardNav {
        height: 3;
        layout: horizontal;
        align: right middle;
        padding: 0 2;
        background: $bg-panel;
        border-top: solid $tool-border;
    }
    WizardNav Button {
        margin: 0 1;
        min-width: 10;
    }
    """

    def compose(self) -> ComposeResult:
        yield Button("← Back", variant="default", id="btn-back")
        yield Button("Next →", variant="primary", id="btn-next")


# ── Step screens ─────────────────────────────────────────────────────────────


class WelcomeScreen(Screen[None]):
    DEFAULT_CSS = """
    WelcomeScreen {
        align: center middle;
    }
    WelcomeScreen #welcome-box {
        background: $bg-panel;
        border: solid $accent;
        padding: 3 6;
        width: 70;
        height: auto;
        align: center middle;
    }
    WelcomeScreen #title {
        text-style: bold;
        color: $accent-bright;
        text-align: center;
        margin-bottom: 1;
    }
    WelcomeScreen #subtitle {
        color: $text-muted;
        text-align: center;
        margin-bottom: 2;
    }
    WelcomeScreen Button {
        align-horizontal: center;
        width: 20;
    }
    """

    def __init__(self, state: WizardState, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = state

    def compose(self) -> ComposeResult:
        with Widget(id="welcome-box"):
            yield Label("CASCADE", id="title")
            yield Static(
                "Welcome to the interactive setup wizard.\n"
                "This will guide you through configuring providers,\n"
                "models, budget, and approval settings.",
                id="subtitle",
            )
            yield Button("Get Started →", variant="primary", id="btn-start")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-start":
            self.app.push_screen(ProviderSelectScreen(state=self.state))


class ProviderSelectScreen(Screen[None]):
    DEFAULT_CSS = """
    ProviderSelectScreen {
        padding: 2 4;
    }
    ProviderSelectScreen #title { color: $accent-bright; text-style: bold; margin-bottom: 1; }
    ProviderSelectScreen #hint { color: $text-muted; margin-bottom: 2; }
    ProviderSelectScreen Checkbox { margin: 0 0 1 0; }
    """

    PROVIDERS = [
        ("anthropic", "Anthropic (Claude)"),
        ("openai", "OpenAI"),
        ("openai-compatible", "OpenAI-compatible endpoint (Groq, Together, etc.)"),
        ("azure", "Azure OpenAI (multi-endpoint)"),
        ("google", "Google (Gemini)"),
        ("ollama", "Ollama (local models)"),
    ]

    def __init__(self, state: WizardState, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = state

    def compose(self) -> ComposeResult:
        yield Label("Select Providers", id="title")
        yield Static("Choose which AI providers to configure (select all that apply):", id="hint")
        for key, label in self.PROVIDERS:
            yield Checkbox(label, value=(key in self.state.providers), id=f"chk-{key}")
        yield WizardNav()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-next":
            selected = []
            for key, _ in self.PROVIDERS:
                cb = self.query_one(f"#chk-{key}", Checkbox)
                if cb.value:
                    selected.append(key)
            if not selected:
                self.notify("Select at least one provider.", severity="warning")
                return
            self.state.providers = selected
            self.app.push_screen(ProviderConfigScreen(state=self.state))
        elif event.button.id == "btn-back":
            self.app.pop_screen()


class LabeledInput(Widget):
    """A labeled text input row."""

    DEFAULT_CSS = """
    LabeledInput { height: auto; margin: 0 0 1 0; }
    LabeledInput Label { color: $text-muted; margin-bottom: 0; }
    LabeledInput Input { background: $bg-input; }
    """

    def __init__(self, label: str, placeholder: str = "", password: bool = False,
                 initial: str = "", input_id: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._placeholder = placeholder
        self._password = password
        self._initial = initial
        self._input_id = input_id

    def compose(self) -> ComposeResult:
        yield Label(self._label)
        yield Input(
            value=self._initial,
            placeholder=self._placeholder,
            password=self._password,
            id=self._input_id or None,
        )

    def get_value(self) -> str:
        return self.query_one(Input).value.strip()


class AzureEndpointForm(Widget):
    """Form for a single Azure endpoint."""

    DEFAULT_CSS = """
    AzureEndpointForm {
        background: $bg-elevated;
        border: solid $tool-border;
        padding: 1 2;
        margin: 0 0 1 0;
        height: auto;
    }
    AzureEndpointForm Label { color: $accent; text-style: bold; margin-bottom: 1; }
    AzureEndpointForm LabeledInput { margin-bottom: 0; }
    """

    def __init__(self, index: int, ep: AzureEndpoint, **kwargs: Any) -> None:
        super().__init__(id=f"ep-form-{index}", **kwargs)
        self._index = index
        self._ep = ep

    def compose(self) -> ComposeResult:
        yield Label(f"Endpoint {self._index + 1}")
        yield LabeledInput("Name", "e.g. eastus-gpt4o", initial=self._ep.name, input_id=f"ep-name-{self._index}")
        yield LabeledInput("Base URL", "https://myresource.openai.azure.com", initial=self._ep.base_url, input_id=f"ep-url-{self._index}")
        yield LabeledInput("API Key", "sk-...", password=True, initial=self._ep.api_key, input_id=f"ep-key-{self._index}")
        yield LabeledInput("API Version", "2024-02-01", initial=self._ep.api_version or "2024-02-01", input_id=f"ep-ver-{self._index}")
        yield LabeledInput("Deployment Name", "gpt-4o", initial=self._ep.deployment_name, input_id=f"ep-dep-{self._index}")
        yield Button("Remove", variant="error", id=f"rm-ep-{self._index}")

    def collect(self) -> AzureEndpoint:
        def val(input_id: str) -> str:
            try:
                return self.query_one(f"#{input_id}", Input).value.strip()
            except Exception:
                return ""
        i = self._index
        return AzureEndpoint(
            name=val(f"ep-name-{i}"),
            base_url=val(f"ep-url-{i}"),
            api_key=val(f"ep-key-{i}"),
            api_version=val(f"ep-ver-{i}") or "2024-02-01",
            deployment_name=val(f"ep-dep-{i}"),
        )


class ProviderConfigScreen(Screen[None]):
    """Per-provider configuration. Shows a section for each selected provider."""

    DEFAULT_CSS = """
    ProviderConfigScreen {
        padding: 2 4;
        overflow-y: auto;
    }
    ProviderConfigScreen #title { color: $accent-bright; text-style: bold; margin-bottom: 1; }
    ProviderConfigScreen #section-label {
        color: $accent;
        text-style: bold;
        margin: 2 0 1 0;
        border-bottom: solid $tool-border;
    }
    ProviderConfigScreen #add-ep-btn { margin: 1 0; }
    """

    def __init__(self, state: WizardState, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = state
        self._ep_count = max(len(state.azure_endpoints), 1)
        if not state.azure_endpoints:
            state.azure_endpoints = [AzureEndpoint()]

    def compose(self) -> ComposeResult:
        yield Label("Configure Providers", id="title")

        if "anthropic" in self.state.providers:
            yield Label("Anthropic", id="section-label")
            yield LabeledInput("API Key", "sk-ant-...", password=True, initial=self.state.anthropic_api_key, input_id="ant-key")
            yield LabeledInput("Model", "claude-sonnet-4-20250514", initial=self.state.anthropic_model, input_id="ant-model")

        if "openai" in self.state.providers:
            yield Label("OpenAI", id="section-label")
            yield LabeledInput("API Key", "sk-...", password=True, initial=self.state.openai_api_key, input_id="oai-key")
            yield LabeledInput("Model", "gpt-4o", initial=self.state.openai_model, input_id="oai-model")
            yield LabeledInput("Base URL (optional)", "https://api.openai.com/v1", initial=self.state.openai_base_url, input_id="oai-url")

        if "openai-compatible" in self.state.providers:
            yield Label("OpenAI-Compatible Endpoint", id="section-label")
            yield LabeledInput("Name", "groq", initial=self.state.compat_name, input_id="compat-name")
            yield LabeledInput("Base URL", "https://api.groq.com/openai/v1", initial=self.state.compat_base_url, input_id="compat-url")
            yield LabeledInput("API Key", "sk-...", password=True, initial=self.state.compat_api_key, input_id="compat-key")
            yield LabeledInput("Model", "llama3-70b-8192", initial=self.state.compat_model, input_id="compat-model")

        if "azure" in self.state.providers:
            yield Label("Azure OpenAI Endpoints", id="section-label")
            for i, ep in enumerate(self.state.azure_endpoints):
                yield AzureEndpointForm(index=i, ep=ep)
            yield Button("+ Add Endpoint", variant="success", id="add-ep-btn")
            yield LabeledInput("Base model (for pricing)", "gpt-4o", initial=self.state.azure_model, input_id="az-model")

        if "google" in self.state.providers:
            yield Label("Google Gemini", id="section-label")
            yield LabeledInput("API Key", "AIza...", password=True, initial=self.state.google_api_key, input_id="goog-key")
            yield LabeledInput("Model", "gemini-2.0-flash", initial=self.state.google_model, input_id="goog-model")

        if "ollama" in self.state.providers:
            yield Label("Ollama", id="section-label")
            yield LabeledInput("Base URL", "http://localhost:11434", initial=self.state.ollama_base_url, input_id="ollama-url")
            yield LabeledInput("Default Model", "qwen2.5-coder:7b", initial=self.state.ollama_model, input_id="ollama-model")

        yield WizardNav()

    def _get(self, input_id: str) -> str:
        try:
            return self.query_one(f"#{input_id}", Input).value.strip()
        except Exception:
            return ""

    def _collect(self) -> None:
        if "anthropic" in self.state.providers:
            self.state.anthropic_api_key = self._get("ant-key")
            self.state.anthropic_model = self._get("ant-model") or "claude-sonnet-4-20250514"
        if "openai" in self.state.providers:
            self.state.openai_api_key = self._get("oai-key")
            self.state.openai_model = self._get("oai-model") or "gpt-4o"
            self.state.openai_base_url = self._get("oai-url")
        if "openai-compatible" in self.state.providers:
            self.state.compat_name = self._get("compat-name") or "custom"
            self.state.compat_base_url = self._get("compat-url")
            self.state.compat_api_key = self._get("compat-key")
            self.state.compat_model = self._get("compat-model") or "gpt-4o"
        if "azure" in self.state.providers:
            eps = []
            for form in self.query(AzureEndpointForm):
                eps.append(form.collect())
            self.state.azure_endpoints = [ep for ep in eps if ep.name]
            self.state.azure_model = self._get("az-model") or "gpt-4o"
        if "google" in self.state.providers:
            self.state.google_api_key = self._get("goog-key")
            self.state.google_model = self._get("goog-model") or "gemini-2.0-flash"
        if "ollama" in self.state.providers:
            self.state.ollama_base_url = self._get("ollama-url") or "http://localhost:11434"
            self.state.ollama_model = self._get("ollama-model") or "qwen2.5-coder:7b"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-next":
            self._collect()
            self.app.push_screen(PlannerSelectScreen(state=self.state))
        elif event.button.id == "btn-back":
            self._collect()
            self.app.pop_screen()
        elif event.button.id == "add-ep-btn":
            self._collect()
            self.state.azure_endpoints.append(AzureEndpoint())
            new_form = AzureEndpointForm(
                index=len(self.state.azure_endpoints) - 1,
                ep=self.state.azure_endpoints[-1],
            )
            add_btn = self.query_one("#add-ep-btn", Button)
            self.mount(new_form, before=add_btn)
        elif event.button.id is not None and event.button.id.startswith("rm-ep-"):
            idx = int(event.button.id.split("-")[-1])
            self._collect()
            if len(self.state.azure_endpoints) > 1:
                self.state.azure_endpoints.pop(idx)
            form = self.query_one(f"#ep-form-{idx}", AzureEndpointForm)
            form.remove()


class PlannerSelectScreen(Screen[None]):
    DEFAULT_CSS = """
    PlannerSelectScreen {
        padding: 2 4;
    }
    PlannerSelectScreen #title { color: $accent-bright; text-style: bold; margin-bottom: 1; }
    PlannerSelectScreen #hint { color: $text-muted; margin-bottom: 2; }
    """

    def __init__(self, state: WizardState, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = state

    def _model_ids(self) -> list[str]:
        ids = []
        if "anthropic" in self.state.providers:
            ids.append("planner")
        if "openai" in self.state.providers:
            ids.append("worker")
        if "openai-compatible" in self.state.providers:
            ids.append(self.state.compat_name or "custom")
        if "azure" in self.state.providers:
            for ep in self.state.azure_endpoints:
                if ep.name:
                    ids.append(f"azure-{ep.name}")
        if "google" in self.state.providers:
            ids.append("gemini")
        if "ollama" in self.state.providers:
            ids.append("local")
        return ids or ["planner"]

    def compose(self) -> ComposeResult:
        yield Label("Default Planner Model", id="title")
        yield Static("Which model should act as the top-level planner?", id="hint")
        ids = self._model_ids()
        with RadioSet(id="planner-radio"):
            for mid in ids:
                yield RadioButton(mid, value=(mid == self.state.default_planner))
        yield WizardNav()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-next":
            rs = self.query_one("#planner-radio", RadioSet)
            if rs.pressed_button:
                self.state.default_planner = str(rs.pressed_button.label)
            self.app.push_screen(BudgetConfigScreen(state=self.state))
        elif event.button.id == "btn-back":
            self.app.pop_screen()


class BudgetConfigScreen(Screen[None]):
    DEFAULT_CSS = """
    BudgetConfigScreen {
        padding: 2 4;
    }
    BudgetConfigScreen #title { color: $accent-bright; text-style: bold; margin-bottom: 1; }
    BudgetConfigScreen #hint { color: $text-muted; margin-bottom: 2; }
    BudgetConfigScreen Checkbox { margin-bottom: 1; }
    BudgetConfigScreen LabeledInput { margin-top: 1; }
    """

    def __init__(self, state: WizardState, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = state

    def compose(self) -> ComposeResult:
        yield Label("Budget Settings", id="title")
        yield Static("Optionally cap spending per session.", id="hint")
        yield Checkbox("Enable budget tracking", value=self.state.budget_enabled, id="budget-enabled")
        yield LabeledInput(
            "Max session cost ($)",
            "5.00",
            initial=str(self.state.budget_max_cost),
            input_id="budget-amount",
        )
        yield WizardNav()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-next":
            self.state.budget_enabled = self.query_one("#budget-enabled", Checkbox).value
            try:
                amt = float(self.query_one("#budget-amount", Input).value.strip() or "5.0")
            except ValueError:
                amt = 5.0
            self.state.budget_max_cost = amt
            self.app.push_screen(ApprovalModeScreen(state=self.state))
        elif event.button.id == "btn-back":
            self.app.pop_screen()


class ApprovalModeScreen(Screen[None]):
    DEFAULT_CSS = """
    ApprovalModeScreen {
        padding: 2 4;
    }
    ApprovalModeScreen #title { color: $accent-bright; text-style: bold; margin-bottom: 1; }
    ApprovalModeScreen #hint { color: $text-muted; margin-bottom: 2; }
    """

    MODES = [
        ("guarded", "Guarded (recommended) — prompt before shell/write operations"),
        ("auto", "Auto — all tools run without prompting"),
        ("strict", "Strict — prompt before every tool call"),
    ]

    def __init__(self, state: WizardState, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = state

    def compose(self) -> ComposeResult:
        yield Label("Approval Mode", id="title")
        yield Static("How much oversight do you want over tool execution?", id="hint")
        with RadioSet(id="mode-radio"):
            for key, label in self.MODES:
                yield RadioButton(label, value=(key == self.state.approval_mode))
        yield WizardNav()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-next":
            rs = self.query_one("#mode-radio", RadioSet)
            if rs.pressed_button:
                label = str(rs.pressed_button.label)
                for key, lbl in self.MODES:
                    if lbl == label:
                        self.state.approval_mode = key
                        break
            self.app.push_screen(ConfirmScreen(state=self.state))
        elif event.button.id == "btn-back":
            self.app.pop_screen()


class ConfirmScreen(Screen[None]):
    DEFAULT_CSS = """
    ConfirmScreen {
        padding: 2 4;
    }
    ConfirmScreen #title { color: $accent-bright; text-style: bold; margin-bottom: 1; }
    ConfirmScreen #hint { color: $text-muted; margin-bottom: 1; }
    ConfirmScreen TextArea {
        height: 20;
        margin-bottom: 2;
    }
    ConfirmScreen #btn-row {
        layout: horizontal;
        height: auto;
    }
    ConfirmScreen Button { margin-right: 1; }
    """

    def __init__(self, state: WizardState, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = state

    def compose(self) -> ComposeResult:
        yaml_text = generate_yaml(self.state)
        if self.state.global_config:
            dest = str(Path.home() / ".cascade" / "config.yaml")
        else:
            dest = str(Path(self.state.target_path) / "cascade.yaml")
        yield Label("Review & Save", id="title")
        yield Static(f"Will be written to: {dest}", id="hint")
        yield TextArea(yaml_text, language="yaml", id="yaml-preview")
        with Widget(id="btn-row"):
            yield Button("← Back", variant="default", id="btn-back")
            yield Button("Save", variant="primary", id="btn-save")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            yaml_text = self.query_one("#yaml-preview", TextArea).text
            if self.state.global_config:
                target = Path.home() / ".cascade" / "config.yaml"
                target.parent.mkdir(parents=True, exist_ok=True)
            else:
                target = Path(self.state.target_path) / "cascade.yaml"
            target.write_text(yaml_text, encoding="utf-8")
            self.notify(f"Saved to {target}", severity="information")
            self.app.exit()
        elif event.button.id == "btn-back":
            self.app.pop_screen()


# ── Root Wizard App ───────────────────────────────────────────────────────────


class InitWizardApp(App[None]):
    """Multi-step cascade init wizard."""

    CSS_PATH = str(Path(__file__).parent.parent / "themes" / "cascade.tcss")
    TITLE = "Cascade Init"

    def __init__(self, target_path: str = ".", global_config: bool = False, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._state = WizardState(target_path=target_path, global_config=global_config)

    def on_mount(self) -> None:
        saved = load_saved_theme()
        if saved != "cascade":
            from cascade.tui.themes import apply_theme
            apply_theme(self, saved)
        self.push_screen(WelcomeScreen(state=self._state))

    def compose(self) -> ComposeResult:
        return iter([])


def load_saved_theme() -> str:
    try:
        from cascade.tui.themes import load_saved_theme as _lst
        return _lst()
    except Exception:
        return "cascade"
