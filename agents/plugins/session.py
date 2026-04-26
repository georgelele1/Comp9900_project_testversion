"""
agents/plugins/session.py — Shared session memory across Whispr agents.

Persists recent context to disk so context survives separate CLI invocations.
Uses storage.session_path() as the single source of truth for the file path.
"""

from __future__ import annotations

import json
import re
import time

from storage import session_path


SESSION_TTL_SECONDS = 60 * 60
_SESSION_MAX = 6
_CONTENT_MAX = 600

_cache: list[dict] | None = None


def _load() -> list[dict]:
    global _cache

    if _cache is not None:
        return _cache

    path = session_path()

    if not path.exists():
        _cache = []
        _save_to_disk(_cache)
        return _cache

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(raw, dict):
            _cache = []
            return _cache

        if time.time() - raw.get("updated_at", 0) > SESSION_TTL_SECONDS:
            _cache = []
            _save_to_disk(_cache)
            return _cache

        messages = raw.get("messages", [])
        _cache = messages if isinstance(messages, list) else []

    except Exception:
        _cache = []

    return _cache


def _save_to_disk(messages: list[dict]) -> None:
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(
            {
                "updated_at": time.time(),
                "messages": messages,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def session_remember(raw: str, output: str) -> None:
    global _cache

    raw = str(raw or "").strip()
    output = str(output or "").strip()

    if not raw or not output:
        return

    session = _load()

    session.append({
        "role": "user",
        "content": raw[:_CONTENT_MAX],
    })

    session.append({
        "role": "assistant",
        "content": output[:_CONTENT_MAX],
    })

    _cache = session[-_SESSION_MAX:]
    _save_to_disk(_cache)


def get_session_context() -> str:
    session = _load()

    if not session:
        return ""

    return "\n".join(
        f"{'User' if item.get('role') == 'user' else 'Assistant'}: {item.get('content', '')}"
        for item in session
    )


def is_followup(text: str) -> bool:
    if not _load():
        return False

    return bool(re.match(
        r"(and |also |now |add |change |remove |translate |send |make it |"
        r"what does|explain|tell me more|what about|how about|"
        r"can you|could you|please |fix |update |shorten |expand |"
        r"write |draft |compose |create )",
        str(text or "").strip(),
        re.IGNORECASE,
    ))


def inject_session(agent) -> None:
    context = get_session_context()

    if context:
        agent.current_session["messages"].append({
            "role": "system",
            "content": f"Recent conversation context:\n{context}",
        })


def clear_session() -> None:
    global _cache

    _cache = []
    _save_to_disk([])