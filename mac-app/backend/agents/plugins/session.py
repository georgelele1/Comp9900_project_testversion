"""
agents/plugins/session.py — Shared session memory across all Whispr agents.

Persists to disk so context survives across separate CLI process invocations.
Uses a module-level cache so the file is read once per process, not on every call.
Session expires after 60 minutes of inactivity.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SESSION_TTL_SECONDS = 60 * 60  # 60 minutes
_SESSION_MAX        = 6        # last 3 exchanges (6 messages)
_CONTENT_MAX        = 600      # chars per message

# Module-level cache — loaded once per process on first access
_cache: list[dict] | None = None


def _session_path() -> Path:
    import os
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support" / "Whispr"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(home))) / "Whispr"
    else:
        base = home / ".local" / "share" / "Whispr"
    base.mkdir(parents=True, exist_ok=True)
    return base / "session.json"


def _load() -> list[dict]:
    """Load session from cache, falling back to disk on first access.
    Creates the file if it does not exist yet.
    """
    global _cache
    if _cache is not None:
        return _cache

    path = _session_path()

    if not path.exists():
        # First launch — create an empty session file
        _save_to_disk([])
        _cache = []
        return _cache

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            _cache = []
            return _cache
        # Expire if idle for more than TTL
        if time.time() - raw.get("updated_at", 0) > SESSION_TTL_SECONDS:
            _save_to_disk([])
            _cache = []
            return _cache
        _cache = raw.get("messages", [])
    except Exception:
        _cache = []

    return _cache


def _save_to_disk(messages: list[dict]) -> None:
    """Write session to disk with current timestamp."""
    try:
        _session_path().write_text(
            json.dumps({"updated_at": time.time(), "messages": messages},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def session_remember(raw: str, output: str) -> None:
    """Store a completed exchange — updates cache and persists to disk."""
    global _cache
    if not raw.strip() or not output.strip():
        return
    session = _load()
    session.append({"role": "user",      "content": raw.strip()[:_CONTENT_MAX]})
    session.append({"role": "assistant", "content": output.strip()[:_CONTENT_MAX]})
    session = session[-_SESSION_MAX:]
    _cache = session
    _save_to_disk(session)


def get_session_context() -> str:
    """Return formatted session history for prompt injection."""
    session = _load()
    if not session:
        return ""
    return "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in session
    )


def is_followup(text: str) -> bool:
    """True if text looks like a continuation of the previous exchange."""
    if not _load():
        return False
    import re
    return bool(re.match(
        r"(and |also |now |add |change |remove |translate |send |make it |"
        r"what does|explain|tell me more|what about|how about|"
        r"can you|could you|please |fix |update |shorten |expand |"
        r"write |draft |compose |create )",
        text.strip(), re.IGNORECASE,
    ))


def inject_session(agent) -> None:
    context = get_session_context()

    if context:
        agent.current_session["messages"].append({
            "role": "system",
            "content": (
                "Recent conversation context is provided below.\n"
                "Decide whether the current user input depends on this context.\n"
                "If the current input is a continuation, correction, rewrite request, tone change, "
                "translation request, shortening/expanding request, or refers to previous content implicitly, "
                "use the previous assistant output as the source text.\n"
                "If the current input is independent, ignore this context.\n\n"
                f"{context}"
            ),
        })


def clear_session() -> None:
    """Clear session — called on reset-all."""
    global _cache
    _cache = []
    _save_to_disk([])