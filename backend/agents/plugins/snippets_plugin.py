"""
agents/plugins/snippets_plugin.py — Voice snippets plugin.

Handles: explicit shortcut expansion by trigger word.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_backend_root = str(_Path(__file__).resolve().parents[2])
if _backend_root not in _sys.path:
    _sys.path.insert(0, _backend_root)

import re
import sys

from agents.plugins.base import WhisprPlugin

_EXPLICIT = re.compile(
    r"^\s*(give me|insert|paste|use|show me|open|pull up)\b",
    re.IGNORECASE,
)


class SnippetsPlugin(WhisprPlugin):
    name        = "snippets"
    description = (
        "Expands user-defined voice shortcuts. User must explicitly request "
        "a shortcut by name using action words like give me, paste, insert, show me. "
        "Only triggers when the user names a known shortcut."
    )
    examples    = [
        "give me my zoom link",
        "paste my email signature",
        "insert company website",
        "show me my gmail",
    ]
    priority    = 30

    def can_handle(self, text: str, context: dict) -> bool:
        if not _EXPLICIT.search(text):
            return False
        triggers = context.get("snippet_triggers", [])
        return any(t.lower() in text.lower() for t in triggers)

    def run(self, text: str, context: dict) -> str:
        try:
            from snippets import load_snippets, DYNAMIC_TRIGGERS
            from gcalendar import get_schedule, load_current_email
            import re

            snippets = {
                item["trigger"].lower(): item["expansion"]
                for item in load_snippets().get("snippets", [])
                if item.get("enabled", True)
            }
            text_lower = text.lower()

            for trigger, expansion in snippets.items():
                if trigger in text_lower:
                    if trigger in DYNAMIC_TRIGGERS:
                        email = load_current_email()
                        return get_schedule(date="today", user_id=email) if email else "No calendar connected."
                    # Format URL snippets naturally
                    if expansion.startswith("http"):
                        label = trigger.title()
                        return f"{label} ({expansion})"
                    return expansion

            return text
        except Exception as e:
            print(f"[snippets] failed: {e}", file=sys.stderr)
            return text


plugin = SnippetsPlugin()