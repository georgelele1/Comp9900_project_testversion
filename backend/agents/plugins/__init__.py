"""
agents/plugins/__init__.py — Plugin registry.

Automatically discovers and loads all plugins in this directory.
Plugins are sorted by priority (lower = checked first).

To add a new plugin:
  1. Create a file in agents/plugins/
  2. Define a class inheriting WhisprPlugin
  3. Export a singleton as `plugin = MyPlugin()`
  4. Done — no other changes needed
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import List

# Ensure backend root is on sys.path so all imports resolve correctly
_backend_root = str(Path(__file__).resolve().parents[2])
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from agents.plugins.base import WhisprPlugin

_PLUGINS: List[WhisprPlugin] = []
_LOADED  = False


def _discover() -> List[WhisprPlugin]:
    """Scan plugins directory and import all plugin modules."""
    plugins    = []
    plugin_dir = Path(__file__).parent

    for path in sorted(plugin_dir.glob("*.py")):
        if path.name.startswith("_") or path.name == "base.py":
            continue
        module_name = f"agents.plugins.{path.stem}"
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "plugin") and isinstance(mod.plugin, WhisprPlugin):
                plugins.append(mod.plugin)
                print(f"[plugins] loaded: {mod.plugin.name} (priority={mod.plugin.priority})", file=sys.stderr)
        except Exception as e:
            print(f"[plugins] failed to load {path.name}: {e}", file=sys.stderr)

    return sorted(plugins, key=lambda p: p.priority)


def get_plugins() -> List[WhisprPlugin]:
    """Return all loaded plugins sorted by priority."""
    global _PLUGINS, _LOADED
    if not _LOADED:
        _PLUGINS = _discover()
        _LOADED  = True
    return _PLUGINS


def find_plugin(text: str, context: dict) -> WhisprPlugin | None:
    """Return the first plugin that can handle this text, or None."""
    for plugin in get_plugins():
        try:
            if plugin.can_handle(text, context):
                print(f"[plugins] → {plugin.name}", file=sys.stderr)
                return plugin
        except Exception as e:
            print(f"[plugins] {plugin.name}.can_handle error: {e}", file=sys.stderr)
    return None