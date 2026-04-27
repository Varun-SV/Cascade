"""cascade doctor — animated health check TUI."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

from textual.app import App, ComposeResult
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Static

from cascade.tui.widgets.doctor_check import CheckResult, DoctorCheckRow, FixFormModal


# ── Check definitions ─────────────────────────────────────────────────────────


@dataclass
class CheckDef:
    check_id: str
    name: str
    run: Callable[..., Coroutine[Any, Any, CheckResult]]
    fix_hint: str = ""
    fix_key: str = ""


async def _check_config(cfg: Any) -> CheckResult:
    return CheckResult(passed=True, detail="Configuration loaded successfully.")


async def _check_project_root(cfg: Any) -> CheckResult:
    root = Path(cfg.project_root)
    ok = root.exists()
    return CheckResult(
        passed=ok,
        detail=f"Project root: {root}" + ("" if ok else " — directory not found"),
        fix_hint="Enter a valid project root path:",
        fix_key="project_root",
    )


async def _check_anthropic(cfg: Any) -> CheckResult:
    ok = bool(cfg.api_keys.anthropic)
    return CheckResult(
        passed=ok,
        detail="Anthropic API key " + ("configured" if ok else "missing"),
        fix_hint="Enter your Anthropic API key (sk-ant-...):",
        fix_key="anthropic_api_key",
    )


async def _check_openai(cfg: Any) -> CheckResult:
    ok = bool(cfg.api_keys.openai)
    return CheckResult(
        passed=ok,
        detail="OpenAI API key " + ("configured" if ok else "missing"),
        fix_hint="Enter your OpenAI API key (sk-...):",
        fix_key="openai_api_key",
    )


async def _check_google(cfg: Any) -> CheckResult:
    ok = bool(cfg.api_keys.google)
    return CheckResult(
        passed=ok,
        detail="Google API key " + ("configured" if ok else "missing"),
        fix_hint="Enter your Google API key (AIza...):",
        fix_key="google_api_key",
    )


async def _check_ollama(cfg: Any) -> CheckResult:
    import httpx
    base_url = cfg.ollama.base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
        ok = resp.status_code == 200
        detail = f"Ollama reachable at {base_url}" if ok else f"Ollama not reachable at {base_url}"
    except Exception as exc:
        ok = False
        detail = f"Ollama unreachable: {exc}"
    return CheckResult(
        passed=ok,
        detail=detail,
        fix_hint=f"Enter Ollama base URL (current: {base_url}):",
        fix_key="ollama_base_url",
    )


async def _check_azure(cfg: Any) -> CheckResult:
    eps = getattr(cfg, "azure_endpoints", [])
    if not eps:
        return CheckResult(passed=True, detail="No Azure endpoints configured.")
    missing = [ep.name for ep in eps if not ep.api_key]
    if missing:
        return CheckResult(
            passed=False,
            detail=f"Azure endpoints missing API keys: {', '.join(missing)}",
            fix_hint="Set environment variables CASCADE_AZURE_<NAME>_API_KEY or update cascade.yaml.",
        )
    return CheckResult(passed=True, detail=f"{len(eps)} Azure endpoint(s) configured.")


def _build_checks(cfg: Any) -> list[CheckDef]:
    checks = [
        CheckDef("config", "Configuration", _check_config),
        CheckDef("project_root", "Project root", _check_project_root,
                 fix_hint="Enter a valid directory path:", fix_key="project_root"),
    ]
    providers = {m.provider for m in cfg.models}
    if "anthropic" in providers:
        checks.append(CheckDef("anthropic", "Anthropic API key", _check_anthropic,
                               fix_hint="Enter your Anthropic API key:", fix_key="anthropic_api_key"))
    if "openai" in providers:
        checks.append(CheckDef("openai", "OpenAI API key", _check_openai,
                               fix_hint="Enter your OpenAI API key:", fix_key="openai_api_key"))
    if "google" in providers:
        checks.append(CheckDef("google", "Google API key", _check_google,
                               fix_hint="Enter your Google API key:", fix_key="google_api_key"))
    if "ollama" in providers:
        checks.append(CheckDef("ollama", "Ollama reachability", _check_ollama))
    if "azure" in providers:
        checks.append(CheckDef("azure", "Azure endpoints", _check_azure))
    return checks


# ── Doctor screen ─────────────────────────────────────────────────────────────


class DoctorScreen(Screen[None]):
    DEFAULT_CSS = """
    DoctorScreen {
        padding: 2 4;
    }
    DoctorScreen #title {
        color: $accent-bright;
        text-style: bold;
        margin-bottom: 2;
    }
    DoctorScreen #summary {
        margin-top: 2;
        color: $text-primary;
        text-style: bold;
        display: none;
    }
    DoctorScreen #btn-exit {
        margin-top: 1;
        display: none;
    }
    DoctorScreen.done #summary { display: block; }
    DoctorScreen.done #btn-exit { display: block; }
    """

    def __init__(self, cfg: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._cfg = cfg
        self._checks = _build_checks(cfg)
        self._results: dict[str, CheckResult] = {}

    def compose(self) -> ComposeResult:
        yield Label("Cascade Doctor", id="title")
        for check_def in self._checks:
            yield DoctorCheckRow(
                check_id=check_def.check_id,
                name=check_def.name,
                on_fix=self._handle_fix,
            )
        yield Static("", id="summary")
        yield Button("Exit", variant="primary", id="btn-exit")

    def on_mount(self) -> None:
        self.run_worker(self._run_checks(), thread=False)

    async def _run_checks(self) -> None:
        for check_def in self._checks:
            try:
                result = await check_def.run(self._cfg)
            except Exception as exc:
                result = CheckResult(passed=False, detail=str(exc),
                                     fix_hint=check_def.fix_hint, fix_key=check_def.fix_key)
            result.fix_hint = result.fix_hint or check_def.fix_hint
            result.fix_key = result.fix_key or check_def.fix_key
            self._results[check_def.check_id] = result
            try:
                row = self.query_one(f"#check-{check_def.check_id}", DoctorCheckRow)
                row.complete(result)
            except Exception:
                pass
            await asyncio.sleep(0.25)

        failed = sum(1 for r in self._results.values() if not r.passed)
        total = len(self._results)
        passed = total - failed
        summary = self.query_one("#summary", Static)
        if failed == 0:
            summary.update(f"[bold green]All {total} checks passed ✓[/bold green]")
        else:
            summary.update(
                f"[bold red]{failed} check(s) failed[/bold red] / [green]{passed} passed[/green]"
                "\nClick Fix next to any failed check to resolve it."
            )
        self.add_class("done")

    def _handle_fix(self, check_id: str, fix_key: str) -> None:
        result = self._results.get(check_id)
        if not result:
            return
        hint = result.fix_hint or f"Fix {check_id}:"

        async def _show_fix() -> None:
            value = await self.app.push_screen_wait(
                FixFormModal(title=f"Fix: {check_id}", hint=hint)
            )
            if value:
                self._apply_fix(fix_key, value, check_id)

        self.run_worker(_show_fix(), thread=False)

    def _apply_fix(self, fix_key: str, value: str, check_id: str) -> None:
        """Write the fix to config and re-run the specific check."""
        import yaml as _yaml  # type: ignore[import-untyped]

        # Find and update the config file
        config_paths = [
            Path.cwd() / "cascade.yaml",
            Path.home() / ".cascade" / "config.yaml",
        ]
        config_path = next((p for p in config_paths if p.exists()), None)
        if config_path:
            try:
                with open(config_path) as f:
                    data = _yaml.safe_load(f) or {}
                if fix_key == "project_root":
                    data["project_root"] = value
                elif fix_key == "anthropic_api_key":
                    data.setdefault("api_keys", {})["anthropic"] = value
                elif fix_key == "openai_api_key":
                    data.setdefault("api_keys", {})["openai"] = value
                elif fix_key == "google_api_key":
                    data.setdefault("api_keys", {})["google"] = value
                elif fix_key == "ollama_base_url":
                    data.setdefault("ollama", {})["base_url"] = value
                with open(config_path, "w") as f:
                    _yaml.dump(data, f, default_flow_style=False, sort_keys=False)
                self.notify(f"Updated {config_path}", severity="information")
            except Exception as exc:
                self.notify(f"Failed to update config: {exc}", severity="error")
                return

        # Reload config and re-run this specific check
        from cascade.config import load_config
        new_cfg = load_config()
        self._cfg = new_cfg
        check_def = next((c for c in self._checks if c.check_id == check_id), None)
        if check_def:
            async def _recheck() -> None:
                try:
                    result = await check_def.run(self._cfg)
                except Exception as exc:
                    result = CheckResult(passed=False, detail=str(exc))
                self._results[check_id] = result
                try:
                    row = self.query_one(f"#check-{check_id}", DoctorCheckRow)
                    row.remove_class("passed", "failed")
                    row.complete(result)
                except Exception:
                    pass
            self.run_worker(_recheck(), thread=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-exit":
            self.app.exit()


# ── Doctor App ────────────────────────────────────────────────────────────────


class DoctorApp(App[None]):
    CSS_PATH = str(Path(__file__).parent.parent / "themes" / "cascade.tcss")
    TITLE = "Cascade Doctor"

    def __init__(self, config_path: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._config_path = config_path

    def on_mount(self) -> None:
        from cascade.tui.themes import apply_theme, load_saved_theme
        saved = load_saved_theme()
        if saved != "cascade":
            apply_theme(self, saved)

        from cascade.config import load_config
        cfg = load_config(self._config_path)
        self.push_screen(DoctorScreen(cfg=cfg))

    def compose(self) -> ComposeResult:
        return iter([])
