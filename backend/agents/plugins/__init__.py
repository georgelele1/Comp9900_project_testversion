"""
agents/plugins/__init__.py — Plugin registry with agent-driven routing.

Two-tier routing:
  Tier 1 (0ms):  Each plugin's can_handle() — fast regex pre-check
  Tier 2 (~7s):  Router agent reads all plugin descriptions and decides

To add a new plugin: create a file, export plugin = MyPlugin(). Done.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import List, Optional

_backend_root = str(Path(__file__).resolve().parents[2])
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from agents.plugins.base import WhisprPlugin

_PLUGINS: List[WhisprPlugin] = []
_LOADED  = False


def _discover() -> List[WhisprPlugin]:
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
                print(f"[plugins] loaded: {mod.plugin.name}", file=sys.stderr)
        except Exception as e:
            print(f"[plugins] failed to load {path.name}: {e}", file=sys.stderr)
    return sorted(plugins, key=lambda p: p.priority)


def get_plugins() -> List[WhisprPlugin]:
    global _PLUGINS, _LOADED
    if not _LOADED:
        _PLUGINS = _discover()
        _LOADED  = True
    return _PLUGINS


def _agent_route(text: str, context: dict) -> Optional[WhisprPlugin]:
    """Use an LLM agent to decide which plugin to call.
    Reads all plugin descriptions and examples, picks the best match.
    Returns None if plain dictation (refiner handles it).
    """
    import io as _io
    _real = sys.stdout
    sys.stdout = _io.StringIO()
    try:
        from connectonion import Agent
    finally:
        sys.stdout = _real

    plugins       = get_plugins()
    plugin_map    = {p.name: p for p in plugins}
    plugin_list   = "\n".join(p.to_prompt_entry() for p in plugins)
    user_context  = context.get("user_context", "")
    session       = context.get("session", "")
    names         = [p.name for p in plugins] + ["refine"]

    agent = Agent(
        model="gpt-5",
        name="whispr_intent_router",
        system_prompt=(
            "You are an intent router for a voice transcription app. "
            "Read the user input and decide which plugin should handle it.\n\n"
            f"Available plugins:\n{plugin_list}\n"
            "- refine: clean and format plain dictation text (DEFAULT)\n\n"
            f"User context: {user_context}\n"
            f"Recent conversation: {session}\n\n"
            f"Reply with ONLY the plugin name. Choose from: {json.dumps(names)}"
        ),
    )
    try:
        choice = str(agent.input(text)).strip().lower().strip('"').strip("'")
        print(f"[plugins] agent chose: {choice}", file=sys.stderr)
        if choice in plugin_map:
            return plugin_map[choice]
        return None  # refine
    except Exception as e:
        print(f"[plugins] agent routing failed: {e}", file=sys.stderr)
        return None


def find_plugin(text: str, context: dict) -> Optional[WhisprPlugin]:
    """Find the right plugin for this text.

    Tier 1: fast regex can_handle() on each plugin (0ms)
    Tier 2: agent reads all descriptions and picks one (~7s)
    """
    # Tier 1 — fast regex pre-checks
    for plugin in get_plugins():
        try:
            if plugin.can_handle(text, context):
                print(f"[plugins] fast-path → {plugin.name}", file=sys.stderr)
                return plugin
        except Exception as e:
            print(f"[plugins] {plugin.name}.can_handle error: {e}", file=sys.stderr)

    # Tier 2 — agent decides based on descriptions
    return _agent_route(text, context)