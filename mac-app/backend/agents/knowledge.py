"""
agents/knowledge.py — Knowledge lookup subagent.

Events:
  after_user_input → inject_profile      (user domain → better answers)
  after_user_input → inject_dictionary   (user may say technical terms)
  after_user_input → generate_expected   (eval plugin)
  before_llm       → inject_language     (language plugin)
  on_complete      → update_profile_background (debounced, daemon)
  on_complete      → show_summary        (visibility plugin)
  on_complete      → evaluate_output     (eval plugin)

No snippet injection — output is an answer, not user dictation.
No dictionary update — output is knowledge, not user speech.
"""
from __future__ import annotations

import re
import sys
import io as _io

_real = sys.stdout
sys.stdout = _io.StringIO()
from connectonion import Agent, after_user_input, before_llm, on_complete
sys.stdout = _real

from agents.profile   import inject_profile, update_profile_background
from agents.dictionary_agent import inject_dictionary
from agents.plugins.lang    import inject_language
from agents.plugins.session  import inject_session, session_remember, is_followup as session_followup
from agents.plugins.visibility import show_summary
from agents.plugins.eval       import generate_expected, evaluate_and_retry

_SESSION: list = []
_SESSION_MAX   = 6


def session_remember(user: str, assistant: str) -> None:
    global _SESSION
    _SESSION.append({"role": "user",      "content": user})
    _SESSION.append({"role": "assistant", "content": assistant})
    _SESSION = _SESSION[-_SESSION_MAX:]


def session_context() -> str:
    if not _SESSION:
        return ""
    return "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content'][:200]}"
        for m in _SESSION
    )


def is_followup(text: str) -> bool:
    if not _SESSION:
        return False
    return bool(re.match(
        r"(what (does|is|are)|explain|tell me more|and |also |now "
        r"|each (character|letter|symbol|variable|term|part|one)"
        r"|what about|how about|give me (an )?example"
        r"|can you explain|break (it|them|this) down"
        r"|what does .{1,20} (mean|stand for|represent))",
        text.strip(), re.IGNORECASE,
    ))


def _set_intent(agent) -> None:
    agent.current_session["whispr_intent"] = "knowledge"


def run(text: str) -> str:
    """Answer a knowledge question."""
    session      = session_context()
    session_hint = f"\n\nConversation so far:\n{session}" if session else ""

    agent = Agent(
        model="gpt-5.4",
        name="whispr_knowledge",
        system_prompt=(
            "You are a universal knowledge assistant covering all domains: "
            "physics, chemistry, math, CS, medicine, finance, law, history, engineering.\n"
            "Rules:\n"
            "1. Follow-ups → resolve from conversation history.\n"
            "2. Formulas → proper notation + variable meanings.\n"
            "3. Steps/processes → numbered list.\n"
            "4. Never start with 'Here is', 'Sure', or any preamble — "
            "first word must be the first word of the actual answer."
            f"{session_hint}"
        ),
        on_events=[
            after_user_input(_set_intent),
            after_user_input(inject_session),
            after_user_input(inject_profile),
            after_user_input(inject_dictionary),
            after_user_input(generate_expected),
            before_llm(inject_language),
            on_complete(update_profile_background),
            on_complete(show_summary),
            on_complete(evaluate_and_retry),
        ],
    )

    result = str(agent.input(text)).strip().strip('"').strip("'")
    result = result if result else text
    session_remember(text, result)
    return result