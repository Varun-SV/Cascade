"""Plugin registry persistence and entry-point loading."""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class PluginRegistry:
    """Persist plugin installation metadata and resolve entry points."""

    def __init__(self, registry_path: str):
        self.registry_path = Path(registry_path).expanduser()
        try:
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Defer write failures until an operation actually needs persistence.
            pass

    def load(self) -> dict[str, Any]:
        """Load the plugin registry file."""
        if not self.registry_path.exists():
            return {"installed": []}
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def save(self, data: dict[str, Any]) -> None:
        """Persist plugin metadata."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def list_plugins(self) -> list[str]:
        """List installed plugin package names."""
        return list(self.load().get("installed", []))

    def install(self, package: str) -> None:
        """Install a plugin package with pip and record it locally."""
        subprocess.run([sys.executable, "-m", "pip", "install", package], check=True)
        data = self.load()
        installed = set(data.get("installed", []))
        installed.add(package)
        data["installed"] = sorted(installed)
        self.save(data)

    def remove(self, package: str) -> None:
        """Uninstall a plugin package and update the registry."""
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", package], check=True)
        data = self.load()
        data["installed"] = [item for item in data.get("installed", []) if item != package]
        self.save(data)

    def inspect(self, package: str) -> dict[str, Any]:
        """Inspect a plugin package's registered entry points."""
        entry_points = importlib.metadata.entry_points()
        info: dict[str, Any] = {"package": package, "entry_points": {}}
        for group in ("cascade.tools", "cascade.providers", "cascade.strategies"):
            matches = []
            for entry_point in entry_points.select(group=group):
                if entry_point.dist and entry_point.dist.name == package:
                    matches.append({"name": entry_point.name, "value": entry_point.value})
            info["entry_points"][group] = matches
        return info

    def load_entry_points(self, group: str) -> dict[str, Any]:
        """Load entry points for a specific Cascade extension group."""
        loaded: dict[str, Any] = {}
        for entry_point in importlib.metadata.entry_points().select(group=group):
            loaded[entry_point.name] = entry_point.load()
        return loaded
