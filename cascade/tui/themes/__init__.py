"""Theme registry and hot-swap for the Cascade TUI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import App

_THEMES_DIR = Path(__file__).parent

THEMES: dict[str, Path] = {
    "cascade": _THEMES_DIR / "cascade.tcss",
    "nord": _THEMES_DIR / "nord.tcss",
    "dracula": _THEMES_DIR / "dracula.tcss",
    "catppuccin-mocha": _THEMES_DIR / "catppuccin_mocha.tcss",
    "gruvbox": _THEMES_DIR / "gruvbox.tcss",
    "tokyo-night": _THEMES_DIR / "tokyo_night.tcss",
    "one-dark": _THEMES_DIR / "one_dark.tcss",
}

_STATE_FILE = Path.home() / ".cascade" / "tui_state.json"


def load_saved_theme() -> str:
    """Return the previously saved theme name, falling back to 'cascade'."""
    try:
        if _STATE_FILE.exists():
            data = json.loads(_STATE_FILE.read_text())
            name = data.get("theme", "cascade")
            if name in THEMES:
                return name
    except Exception:
        pass
    return "cascade"


def save_theme(name: str) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if _STATE_FILE.exists():
            data = json.loads(_STATE_FILE.read_text())
        data["theme"] = name
        _STATE_FILE.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def apply_theme(app: "App", name: str) -> bool:
    """Hot-swap the TUI theme. Returns True on success."""
    path = THEMES.get(name)
    if path is None:
        return False
    try:
        css = path.read_text()
        app.stylesheet.source = {str(path): css}  # type: ignore[attr-defined]
        app.refresh_css()
        save_theme(name)
        return True
    except Exception:
        return False


def theme_names() -> list[str]:
    return list(THEMES.keys())
