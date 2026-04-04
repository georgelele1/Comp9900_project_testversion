"""
agents/plugins/base.py — Plugin base class.

Every plugin must:
  1. Inherit from WhisprPlugin
  2. Define `name`, `description`, `triggers`
  3. Implement `can_handle(text)` → bool
  4. Implement `run(text, **context)` → str

To add a new plugin:
  - Create a new file in agents/plugins/
  - Inherit WhisprPlugin
  - The router discovers it automatically
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_backend_root = str(_Path(__file__).resolve().parents[2])
if _backend_root not in _sys.path:
    _sys.path.insert(0, _backend_root)
from abc import ABC, abstractmethod


class WhisprPlugin(ABC):
    """Base class for all Whispr plugins."""

    # ── Plugin metadata ───────────────────────────────────
    name        : str = ""   # unique plugin name e.g. "knowledge"
    description : str = ""   # what this plugin does
    priority    : int = 50   # lower = checked first (0-100)

    # ── Abstract interface ────────────────────────────────

    @abstractmethod
    def can_handle(self, text: str, context: dict) -> bool:
        """Return True if this plugin should handle the given text.

        Args:
            text:    Pre-cleaned input text.
            context: Dict with keys: session_memory, snippet_triggers,
                     user_context, app_name, target_language.
        """
        ...

    @abstractmethod
    def run(self, text: str, context: dict) -> str:
        """Execute the plugin and return the result.

        Args:
            text:    Pre-cleaned input text.
            context: Same context dict as can_handle.

        Returns:
            Final output string to be pasted.
        """
        ...

    def __repr__(self) -> str:
        return f"<Plugin:{self.name} priority={self.priority}>"