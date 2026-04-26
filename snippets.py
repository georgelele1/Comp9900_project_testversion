"""
snippets.py — Voice shortcuts for Whispr.

Examples:
- trigger: "zoom link"
- expansion: "Zoom link: https://zoom.us/j/xxxx"

Storage:
- Uses storage.snippets_path()
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict

from storage import snippets_path


def load_snippets() -> Dict[str, Any]:
    path = snippets_path()

    if not path.exists():
        return {"snippets": []}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"snippets": []}
    except Exception:
        return {"snippets": []}


def save_snippets(data: Dict[str, Any]) -> None:
    snippets_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_all() -> Dict[str, Any]:
    data = load_snippets()
    snippets = data.get("snippets", [])

    return {
        "ok": True,
        "snippets": snippets,
        "count": len(snippets),
    }


def add_snippet(trigger: str, expansion: str) -> Dict[str, Any]:
    trigger = str(trigger or "").strip()
    expansion = str(expansion or "").strip()

    if not trigger:
        return {"ok": False, "error": "trigger is required"}

    if not expansion:
        return {"ok": False, "error": "expansion text is required"}

    data = load_snippets()
    snippets = data.get("snippets", [])

    for item in snippets:
        if str(item.get("trigger", "")).lower() == trigger.lower():
            item["expansion"] = expansion
            item["enabled"] = True
            save_snippets(data)
            return {"ok": True, "updated": True, "snippet": item}

    entry = {
        "trigger": trigger,
        "expansion": expansion,
        "enabled": True,
    }

    snippets.append(entry)
    data["snippets"] = snippets
    save_snippets(data)

    return {"ok": True, "updated": False, "snippet": entry}


def remove_snippet(trigger: str) -> Dict[str, Any]:
    trigger = str(trigger or "").strip()

    if not trigger:
        return {"ok": False, "error": "trigger is required"}

    data = load_snippets()
    snippets = data.get("snippets", [])

    filtered = [
        item for item in snippets
        if str(item.get("trigger", "")).lower() != trigger.lower()
    ]

    if len(filtered) == len(snippets):
        return {"ok": False, "error": f"snippet not found: {trigger}"}

    data["snippets"] = filtered
    save_snippets(data)

    return {
        "ok": True,
        "removed": trigger,
        "remaining": len(filtered),
    }


def toggle_snippet(trigger: str, enabled: bool = True) -> Dict[str, Any]:
    trigger = str(trigger or "").strip()

    if not trigger:
        return {"ok": False, "error": "trigger is required"}

    data = load_snippets()

    for item in data.get("snippets", []):
        if str(item.get("trigger", "")).lower() == trigger.lower():
            item["enabled"] = bool(enabled)
            save_snippets(data)

            return {
                "ok": True,
                "trigger": trigger,
                "enabled": item["enabled"],
            }

    return {"ok": False, "error": f"snippet not found: {trigger}"}


# =========================================================
# CLI
# =========================================================

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "cli":
        print("usage: python snippets.py cli <command> [args...]")
        print("commands: list, add, remove, toggle")
        sys.exit(1)

    command = sys.argv[2] if len(sys.argv) > 2 else "list"

    if command == "list":
        print(json.dumps(list_all(), ensure_ascii=False))

    elif command == "add":
        trigger = sys.argv[3] if len(sys.argv) > 3 else ""
        expansion = sys.argv[4] if len(sys.argv) > 4 else ""
        print(json.dumps(add_snippet(trigger, expansion), ensure_ascii=False))

    elif command == "remove":
        trigger = sys.argv[3] if len(sys.argv) > 3 else ""
        print(json.dumps(remove_snippet(trigger), ensure_ascii=False))

    elif command == "toggle":
        trigger = sys.argv[3] if len(sys.argv) > 3 else ""
        enabled_raw = sys.argv[4] if len(sys.argv) > 4 else "true"
        enabled = enabled_raw.lower() in ("1", "true", "yes", "on")
        print(json.dumps(toggle_snippet(trigger, enabled), ensure_ascii=False))

    else:
        print(json.dumps({
            "ok": False,
            "error": f"unknown command: {command}",
        }, ensure_ascii=False))
        sys.exit(1)